"""Reader spike (#8): vision alone, OCR alone, and vision + format rule on 10 tuning photos.

How to run (Ollama running, models pulled, tesseract installed):
    python -m amber_lens.perception.spike
    python -m amber_lens.perception.spike --models qwen2.5vl:3b --json-out docs/reader_spike_results.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from amber_lens.perception.cache import ResponseCache
from amber_lens.perception.config import Settings, load_settings
from amber_lens.perception.dataset import LabelRow, load_tuning_labels, tuning_photo_path
from amber_lens.perception.fields import KEY_FIELDS, LABELLED_FIELDS
from amber_lens.perception.locate import locate
from amber_lens.perception.ocr import OcrLine, OcrResult, run_tesseract
from amber_lens.perception.rules import check_format
from amber_lens.perception.scoring import WRONG_OUTCOMES, Outcome, score_field, tally
from amber_lens.perception.textfields import extract_fields
from amber_lens.perception.vision import SPIKE_PROMPT, OllamaVision, VisionError, gpu_share, parse_reading

# Chosen to cover glare, small text, blur, an angled plate, a compressor, a transformer, an AC unit
# and one plate the labels mark unreadable.
SPIKE_PHOTOS: tuple[str, ...] = (
    "hf_02", "hf_04", "hf_06", "hf_053", "hf_066", "hf_069", "hf_259", "darjja_train_01", "darjja_train_10",
    "hf_295",
)
DEFAULT_MODELS: tuple[str, ...] = ("qwen2.5vl:3b", "qwen3-vl:4b")
OCR_ARM = "ocr"


@dataclass(frozen=True)
class ArmReading:
    arm: str
    photo_id: str
    values: dict[str, str | None]
    latency_ms: int
    error: str | None = None


@dataclass(frozen=True)
class ModelRun:
    model: str
    cold_load_ms: int | None
    gpu_share: float | None
    cached_calls: int


def vision_arm(model: str) -> str:
    return f"vision:{model}"


def rule_arm(model: str) -> str:
    return f"vision+rule:{model}"


def located_arm(model: str) -> str:
    return f"vision+rule+located:{model}"


def apply_format_rules(values: dict[str, str | None]) -> dict[str, str | None]:
    """Keep a value only when its field's format rule passes; never repair it."""
    return {name: (value if check_format(name, value) else None) for name, value in values.items()}


def keep_located(values: dict[str, str | None], lines: tuple[OcrLine, ...]) -> dict[str, str | None]:
    """Keep a value only when OCR finds it printed on the photo; the strict READ condition from T2-1."""
    return {
        name: (value if value is not None and locate(name, value, lines) is not None else None)
        for name, value in values.items()
    }


def score_arm(readings: list[ArmReading], labels: dict[str, LabelRow], fields: tuple[str, ...]) -> dict:
    """Field -> Counter of outcomes for one arm."""
    return {
        field: tally([score_field(field, r.values.get(field), labels[r.photo_id].truth[field]) for r in readings])
        for field in fields
    }


def disagreements(readings: list[ArmReading], labels: dict[str, LabelRow], fields: tuple[str, ...]) -> list[dict]:
    rows = []
    for r in readings:
        for field in fields:
            truth = labels[r.photo_id].truth[field]
            outcome = score_field(field, r.values.get(field), truth)
            if outcome in WRONG_OUTCOMES:
                rows.append(
                    {"arm": r.arm, "photo_id": r.photo_id, "field": field, "label": truth,
                     "read": r.values.get(field), "outcome": outcome.value}
                )
    return rows


def latency_summary(latencies_ms: list[int]) -> dict[str, float]:
    seconds = [ms / 1000 for ms in latencies_ms]
    return {"mean_s": round(statistics.mean(seconds), 2), "median_s": round(statistics.median(seconds), 2),
            "max_s": round(max(seconds), 2)}


def run_models(
    settings: Settings, models: tuple[str, ...], photos: dict[str, Path], ocr: dict[str, OcrResult]
) -> tuple[list[ArmReading], list[ModelRun]]:
    """Run each model over every photo, one model at a time so each gets the whole GPU."""
    cache = ResponseCache(settings.cache_dir / "vision")
    readings: list[ArmReading] = []
    runs: list[ModelRun] = []
    for model in models:
        client = OllamaVision(settings.ollama_host, model, cache)
        cold_load_ms = None
        share = None
        cached = 0
        for photo_id, path in photos.items():
            call = client.read(path, SPIKE_PROMPT)
            cached += int(call.cached)
            if not call.cached and cold_load_ms is None:
                cold_load_ms = call.load_ms
                share = gpu_share(settings.ollama_host, model)
            try:
                values = parse_reading(call.raw_text, SPIKE_PROMPT.fields)
                error = None
            except VisionError as exc:
                values = {name: None for name in SPIKE_PROMPT.fields}
                error = str(exc)
            readings.append(ArmReading(vision_arm(model), photo_id, values, call.latency_ms, error))
            ruled = apply_format_rules(values)
            readings.append(ArmReading(rule_arm(model), photo_id, ruled, call.latency_ms, error))
            located = keep_located(ruled, ocr[photo_id].lines)
            # The located arm pays for one OCR pass on top of the vision call.
            readings.append(
                ArmReading(located_arm(model), photo_id, located, call.latency_ms + ocr[photo_id].latency_ms, error)
            )
        if cached < len(photos):
            client.unload()
        runs.append(ModelRun(model=model, cold_load_ms=cold_load_ms, gpu_share=share, cached_calls=cached))
    return readings, runs


def ocr_readings(ocr: dict[str, OcrResult]) -> list[ArmReading]:
    readings = []
    for photo_id, result in ocr.items():
        hits = extract_fields(result.lines)
        values = {name: (hit.value if (hit := hits.get(name)) else None) for name in LABELLED_FIELDS}
        readings.append(ArmReading(OCR_ARM, photo_id, values, result.latency_ms))
    return readings


def _counts_row(label: str, counts: Counter) -> str:
    cells = " | ".join(str(counts[o]) for o in Outcome)
    return f"| {label} | {cells} |"


def render_markdown(readings: list[ArmReading], labels: dict[str, LabelRow], arms: list[str]) -> str:
    out = ["## Key fields (model number + 2 ratings), counts over 10 photos x 3 fields", "",
           "| arm | correct | wrong | extra | missed | abstained ok | wrong READs | latency mean / median / max (s) |",
           "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for arm in arms:
        arm_readings = [r for r in readings if r.arm == arm]
        total: Counter = Counter()
        for counts in score_arm(arm_readings, labels, KEY_FIELDS).values():
            total.update(counts)
        lat = latency_summary([r.latency_ms for r in arm_readings])
        wrong = total[Outcome.WRONG] + total[Outcome.EXTRA]
        out.append(
            f"| {arm} | {total[Outcome.CORRECT]} | {total[Outcome.WRONG]} | {total[Outcome.EXTRA]} | "
            f"{total[Outcome.MISSED]} | {total[Outcome.ABSTAINED_OK]} | {wrong} | "
            f"{lat['mean_s']} / {lat['median_s']} / {lat['max_s']} |"
        )
    out += ["", "## Per field, per arm", "", "| arm / field | " + " | ".join(o.value for o in Outcome) + " |",
            "| --- | " + " | ".join("---" for _ in Outcome) + " |"]
    for arm in arms:
        arm_readings = [r for r in readings if r.arm == arm]
        for field, counts in score_arm(arm_readings, labels, LABELLED_FIELDS).items():
            out.append(_counts_row(f"{arm} / {field}", counts))
    out += ["", "## Disagreements with labels (wrong or extra)", "", "| arm | photo | field | label | read |",
            "| --- | --- | --- | --- | --- |"]
    for row in disagreements(readings, labels, LABELLED_FIELDS):
        out.append(f"| {row['arm']} | {row['photo_id']} | {row['field']} | {row['label']} | {row['read']} |")
    errors = [r for r in readings if r.error]
    if errors:
        out += ["", "## Unparseable answers", ""] + [f"- {r.arm} {r.photo_id}: {r.error}" for r in errors]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reader spike on 10 tuning photos (#8)")
    parser.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS))
    parser.add_argument("--json-out", type=Path, default=None, help="write all readings and run info as JSON")
    args = parser.parse_args(argv)

    settings = load_settings()
    labels = load_tuning_labels(settings.data_dir)
    missing = [p for p in SPIKE_PHOTOS if p not in labels]
    if missing:
        print(f"spike photos not in the tuning labels: {missing}", file=sys.stderr)
        return 2
    photos = {photo_id: tuning_photo_path(settings.data_dir, labels[photo_id]) for photo_id in SPIKE_PHOTOS}

    models = tuple(args.models)
    ocr = {photo_id: run_tesseract(path) for photo_id, path in photos.items()}
    ocr_engine = next(iter(ocr.values())).engine
    vision_readings, runs = run_models(settings, models, photos, ocr)
    readings = vision_readings + ocr_readings(ocr)
    arms = [arm for model in models for arm in (vision_arm(model), rule_arm(model), located_arm(model))] + [OCR_ARM]

    print(f"prompt {SPIKE_PROMPT.version}; OCR {ocr_engine}; cost_usd 0.0 for every arm (all local)")
    for run in runs:
        print(f"{run.model}: cold load {run.cold_load_ms} ms, GPU share {run.gpu_share}, cached calls {run.cached_calls}/10")
    print()
    print(render_markdown(readings, labels, arms))

    if args.json_out is not None:
        payload = {
            "prompt_version": SPIKE_PROMPT.version,
            "ocr_engine": ocr_engine,
            "photos": list(SPIKE_PHOTOS),
            "model_runs": [asdict(run) for run in runs],
            "labels": {photo_id: labels[photo_id].truth for photo_id in SPIKE_PHOTOS},
            "readings": [asdict(r) for r in readings],
        }
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
