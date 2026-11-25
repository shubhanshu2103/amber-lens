"""Reader eval on the tuning split (#11): every tuning photo through read_nameplate, counts per field.

A labels.csv model_number matches when either READ identifier (catalog_number or model_number) equals
it; which one matched is reported. A READ value that disagrees with the label, or a READ where the
label says the field is not printed, is a wrong READ.

How to run:
    python -m amber_lens.perception.evaluate --ocr both --json-out docs/perception_eval_tuning.json
    python -m amber_lens.perception.evaluate --ocr tesseract
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from amber_lens.perception.config import load_settings
from amber_lens.perception.crops import run_both_with_crops, run_tesseract_with_crops
from amber_lens.perception.dataset import LabelRow, load_tuning_labels, tuning_photo_path
from amber_lens.perception.fields import IDENTIFIER_FIELDS, KEY_FIELDS, LABELLED_FIELDS
from amber_lens.perception.ocr import run_multipass, run_rapidocr, run_rapidocr_and_tesseract
from amber_lens.perception.reader import NameplateRun, run_nameplate
from amber_lens.perception.scoring import Outcome, values_agree
from amber_lens.perception.spike import SPIKE_PHOTOS
from amber_lens.schemas import ReadStatus

OCR_RUNNERS = {
    "tesseract": run_multipass,
    "rapidocr": run_rapidocr,
    "both": run_rapidocr_and_tesseract,
    "tesseract+crops": run_tesseract_with_crops,
    "both+crops": run_both_with_crops,
}


@dataclass(frozen=True)
class FieldScore:
    photo_id: str
    field: str
    outcome: Outcome
    read_value: str | None
    truth: str | None
    matched_via: str | None
    located_by: str | None


def _read_values(run: NameplateRun) -> dict[str, str | None]:
    return {f.name: (f.value if f.status == ReadStatus.READ else None) for f in run.result.fields}


def score_photo(photo_id: str, run: NameplateRun, row: LabelRow) -> list[FieldScore]:
    values = _read_values(run)
    scores = []
    for field in LABELLED_FIELDS:
        truth = row.truth[field]
        candidates = IDENTIFIER_FIELDS if field == "model_number" else (field,)
        read = [(name, values[name]) for name in candidates if values.get(name) is not None]
        matched = next((name for name, value in read if truth is not None and values_agree("model_number"
                        if name in IDENTIFIER_FIELDS else field, value, truth)), None)
        if matched is not None:
            outcome, shown, path = Outcome.CORRECT, values[matched], run.located_by[matched]
        elif read:
            outcome = Outcome.WRONG if truth is not None else Outcome.EXTRA
            shown, path = " | ".join(v for _, v in read), run.located_by[read[0][0]]
        else:
            outcome, shown, path = (Outcome.MISSED if truth is not None else Outcome.ABSTAINED_OK), None, None
        scores.append(FieldScore(photo_id, field, outcome, shown, truth, matched, path))
    return scores


def key_located(runs: dict[str, NameplateRun], labels: dict[str, LabelRow]) -> tuple[int, int]:
    """(key values with a located box, labelled key values); an identifier counts once per photo."""
    located = labelled = 0
    for photo_id, run in runs.items():
        for field in KEY_FIELDS:
            if labels[photo_id].truth[field] is None:
                continue
            labelled += 1
            names = IDENTIFIER_FIELDS if field == "model_number" else (field,)
            located += any(run.located_by[name] is not None for name in names)
    return located, labelled


def rule_cost(runs: dict[str, NameplateRun], labels: dict[str, LabelRow], rule: str) -> dict[str, tuple[int, int]]:
    """Per rating field: (values this rule alone moved out of READ, of which the vision value was correct)."""
    cost = {}
    for field in ("voltage", "rated_current", "frequency"):
        moved = correct = 0
        for photo_id, run in runs.items():
            if run.rules[field] != rule:
                continue
            moved += 1
            value = next(f.vision_value for f in run.result.fields if f.name == field)
            truth = labels[photo_id].truth[field]
            correct += bool(value and truth and values_agree(field, value, truth))
        cost[field] = (moved, correct)
    return cost


def reason_counts(runs: dict[str, NameplateRun]) -> dict[str, Counter]:
    counts: dict[str, Counter] = {}
    for run in runs.values():
        for field, reason in run.reasons.items():
            counts.setdefault(field, Counter())[reason or "READ"] += 1
    return counts


def located_counts(runs: dict[str, NameplateRun]) -> Counter:
    return Counter(path for run in runs.values() for path in run.located_by.values() if path is not None)


def _paths_and_rules(
    scores: list[FieldScore], wrong: list[FieldScore], runs: dict[str, NameplateRun], labels: dict[str, LabelRow]
) -> list[str]:
    located, labelled = key_located(runs, labels)
    correct_by_path = Counter(s.located_by for s in scores if s.outcome is Outcome.CORRECT)
    out = ["", f"key values located: {located} of {labelled} labelled ({100 * located / labelled:.0f}%)",
           f"located boxes per path, all fields: {dict(located_counts(runs))}",
           f"correct READs per path: {dict(correct_by_path)}",
           f"wrong READs per path: {dict(Counter(s.located_by for s in wrong))}"]
    for field, (moved, was_correct) in rule_cost(runs, labels, "multi_rating").items():
        out.append(f"R4 multi_rating, {field}: moved {moved} out of READ, {was_correct} of them correct")
    warned = sorted(pid for pid, run in runs.items() if any(run.warnings.values()))
    out.append(f"multi_row_table warnings: {len(warned)} photos ({', '.join(warned)})")
    flagged = sorted(pid for pid, run in runs.items() if any(f.injection_flag for f in run.result.fields))
    out.append(f"injection flags: {len(flagged)} photos ({', '.join(flagged)})")
    return out


def render(scores: list[FieldScore], runs: dict[str, NameplateRun], labels: dict[str, LabelRow]) -> str:
    out = [f"photos read: {len(runs)}", "",
           "| field | correct | wrong | extra | missed | abstained ok |", "| --- | --- | --- | --- | --- | --- |"]
    for field in LABELLED_FIELDS:
        c = Counter(s.outcome for s in scores if s.field == field)
        out.append(f"| {field} | {c[Outcome.CORRECT]} | {c[Outcome.WRONG]} | {c[Outcome.EXTRA]} | "
                   f"{c[Outcome.MISSED]} | {c[Outcome.ABSTAINED_OK]} |")
    wrong = [s for s in scores if s.outcome in (Outcome.WRONG, Outcome.EXTRA)]
    key = [s for s in scores if s.field in KEY_FIELDS]
    key_labelled = [s for s in key if s.truth is not None]
    key_correct = [s for s in key if s.outcome is Outcome.CORRECT]
    via = Counter(s.matched_via for s in scores if s.field == "model_number" and s.matched_via)
    key_wrong = sum(1 for s in wrong if s.field in KEY_FIELDS)
    columns = ("READ", "model_missing", "format_fail", "not_located", "readers_disagree")
    out += [
        "",
        f"wrong READs, all fields: {len(wrong)}; key fields: {key_wrong}",
        f"key values READ and correct: {len(key_correct)} of {len(key_labelled)} labelled",
        f"model_number matched via: {dict(via)}",
        "",
        "| field | " + " | ".join(columns) + " |",
        "| --- " * (len(columns) + 1) + "|",
    ]
    for field, c in reason_counts(runs).items():
        out.append(f"| {field} | " + " | ".join(str(c[col]) for col in columns) + " |")
    def mean(key: str) -> float:
        return statistics.mean(run.timings[key] for run in runs.values()) / 1000

    latencies = [run.result.latency_ms / 1000 for run in runs.values()]
    latency = (f"mean {statistics.mean(latencies):.2f}, median {statistics.median(latencies):.2f}, "
               f"max {max(latencies):.2f} (vision {mean('vision_ms'):.2f}, OCR {mean('ocr_ms'):.2f} in parallel); "
               f"tokens per photo {mean('tokens') * 1000:.0f}")
    out += _paths_and_rules(scores, wrong, runs, labels)
    cost = statistics.mean(run.result.cost_usd for run in runs.values())
    out += ["", f"latency per photo (s): {latency}; cost_usd per photo: {cost:.5f}", "", "wrong READs:"]
    out += [f"- {s.photo_id} {s.field}: read {s.read_value!r}, label {s.truth!r}, via {s.located_by}" for s in wrong]
    out += [] if wrong else ["- none"]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reader eval on all tuning photos (#11)")
    parser.add_argument("--ocr", choices=sorted(OCR_RUNNERS), default="both")
    parser.add_argument("--photos", choices=("all", "spike"), default="all", help="spike = the 10 photos of #8")
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args(argv)
    settings = load_settings()
    labels = load_tuning_labels(settings.data_dir)
    if not labels:
        print("no tuning rows in labels.csv", file=sys.stderr)
        return 2
    runs = {
        photo_id: run_nameplate(
            tuning_photo_path(settings.data_dir, labels[photo_id]), settings=settings, ocr=OCR_RUNNERS[args.ocr]
        )
        for photo_id in (sorted(labels) if args.photos == "all" else SPIKE_PHOTOS)
    }
    scores = [s for photo_id, run in runs.items() for s in score_photo(photo_id, run, labels[photo_id])]
    model = settings.groq_model if settings.vision_provider == "groq" else settings.vision_model
    print(f"provider {settings.vision_provider}; model {model}; OCR {args.ocr}; photos {args.photos}")
    print(render(scores, runs, labels))
    if args.json_out is not None:
        payload = {
            "model": settings.vision_model,
            "ocr": args.ocr,
            "runs": {pid: {"result": json.loads(run.result.model_dump_json()), "reasons": run.reasons,
                           "rules": run.rules, "located_by": run.located_by,
                           "warnings": run.warnings} for pid, run in runs.items()},
            "scores": [s.__dict__ | {"outcome": s.outcome.value} for s in scores],
        }
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
