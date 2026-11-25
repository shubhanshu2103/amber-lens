"""Nameplate reader (#11) and the shared core for every document kind.

READ only when every check passes (reason when one fails): the model gave a value (model_missing); format
rule, ratings hold only unit words (R3, format_fail); OCR finds it, box >= 8 px and 60% of the median line
(R2, not_located); not a fragment (R1), OCR read the same characters, OCR's reading under the label agrees, no
2+ different ratings (R4) (readers_disagree); an attached power unit sits next to its number and an identifier
has its label left or above (R5) (not_located); never on a flagged line (#12, injection_flag). Vision provider
failure: every field DISPUTED, vision_unavailable. Failures have value None; OCR never READs alone.

run_nameplate returns result, reasons (None = READ), rules, located_by, warnings (multi_row_table, vision) and
timings; vision and OCR run in parallel. Run: python -m amber_lens.perception.reader <photo> --out <json>
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from amber_lens.perception.config import Settings, load_settings
from amber_lens.perception.crops import CROP_PASS
from amber_lens.perception.dataset import ensure_not_heldout
from amber_lens.perception.fields import IDENTIFIER_FIELDS, NAMEPLATE_FIELDS
from amber_lens.perception.injection import flagged_lines, free_text_fields, on_flagged_line
from amber_lens.perception.locate import (
    LocateHit,
    has_label_anchor,
    has_rating_table,
    locate,
    min_box_height,
    strict_key,
    unit_adjacent,
)
from amber_lens.perception.ocr import RAPID_PASS, OcrLine, OcrResult, run_rapidocr_and_tesseract
from amber_lens.perception.rules import allowed_label, attach_power_unit, check_format
from amber_lens.perception.textfields import all_values, extract_fields
from amber_lens.perception.vision import (
    NAMEPLATE_PROMPT,
    FieldReading,
    VisionCall,
    VisionError,
    VisionPrompt,
    parse_labelled_reading,
)
from amber_lens.schemas import PerceptionResult, ReadField, ReadStatus, SourceRef

FULL_OCR = "full_ocr"
RAPIDOCR = "rapidocr"
CROP_OCR = "crop_ocr"
MULTI_RATING_FIELDS = ("voltage", "rated_current", "frequency")


class Reason(str, Enum):
    FORMAT_FAIL = "format_fail"
    READERS_DISAGREE = "readers_disagree"
    NOT_LOCATED = "not_located"
    MODEL_MISSING = "model_missing"
    VISION_UNAVAILABLE = "vision_unavailable"


class PerceptionError(RuntimeError):
    """The photo cannot be read at all (missing file, unsupported observation kind)."""


class VisionReader(Protocol):
    model: str

    def read(self, image_path: Path, prompt: VisionPrompt) -> VisionCall: ...


OcrRunner = Callable[[Path], OcrResult]


@dataclass(frozen=True)
class OcrEvidence:
    """Everything OCR says about one photo, gathered once and shared by every field decision."""

    lines: tuple[OcrLine, ...]
    hints: dict[str, str | None]
    candidates: dict[str, tuple[str, ...]]
    min_box_height: float
    rating_table: bool
    flagged: list[OcrLine]


@dataclass(frozen=True)
class FieldDecision:
    field: ReadField
    reason: Reason | None
    rule: str | None
    located_by: str | None


@dataclass(frozen=True)
class NameplateRun:
    result: PerceptionResult
    reasons: dict[str, str | None]
    rules: dict[str, str | None]
    located_by: dict[str, str | None]
    warnings: dict[str, str | None]
    timings: dict[str, int] | None = None


def _distinct_rule_passing(field: str, values: list[str]) -> tuple[str, ...]:
    seen: dict[str, str] = {}
    for value in values:
        key = strict_key(field, value)
        if key and key not in seen and check_format(field, value):
            seen[key] = value
    return tuple(seen.values())


def build_evidence(ocr: OcrResult) -> OcrEvidence:
    # Crop re-reads only help locate a value; hints, R4 candidates and box heights use full-image lines.
    full = tuple(line for line in ocr.lines if line.pass_id != CROP_PASS)
    hints = extract_fields([line for line in ocr.lines if line.pass_id == ocr.primary_pass])
    return OcrEvidence(
        lines=ocr.lines,
        hints={name: (hit.value if (hit := hints.get(name)) else None) for name in NAMEPLATE_FIELDS},
        candidates={name: _distinct_rule_passing(name, all_values(name, full)) for name in MULTI_RATING_FIELDS},
        min_box_height=min_box_height(full),
        rating_table=has_rating_table(full),
        flagged=flagged_lines(ocr.lines, ocr.primary_pass),
    )


def ocr_path(pass_id: str) -> str:
    return {RAPID_PASS: RAPIDOCR, CROP_PASS: CROP_OCR}.get(pass_id, FULL_OCR)


def field_stop(name: str, status: ReadStatus, reason: Reason, rule: str, located_by: str | None = None,
          **fields) -> FieldDecision:
    return FieldDecision(ReadField(name=name, value=None, status=status, **fields), reason, rule, located_by)


def _check_located(
    name: str, value: str, attached: bool, label: str | None, hit: LocateHit, hint: str | None, evidence: OcrEvidence,
    anchored: frozenset[str],
) -> tuple[Reason, str, str | None, bool] | None:
    """Checks after the value is found: (reason, rule, ocr_value, keep the source) for the first that fails."""
    if hit.fragment:
        return Reason.READERS_DISAGREE, "fragment", hit.ocr_text, True
    if not hit.exact:
        return Reason.READERS_DISAGREE, "glyph_mismatch", hit.ocr_text, True
    # Every power value needs its unit confirmed next to the number, whoever wrote the unit (T2-8).
    unit = label if attached else next(iter(re.findall(r"(?i)(?<![a-z])(?:hp|kva|kw|va|w)(?![a-z])", value)), "")
    if name == "power" and not unit_adjacent(hit, unit or ""):
        return Reason.NOT_LOCATED, "unit_not_adjacent", hit.ocr_text, False
    if name in anchored and not has_label_anchor(name, hit, evidence.lines):
        return Reason.NOT_LOCATED, "label_anchor_missing", hit.ocr_text, False
    if hint is not None and check_format(name, hint) and strict_key(name, hint) != strict_key(name, value):
        return Reason.READERS_DISAGREE, "ocr_label_value_differs", hint, True
    candidates = evidence.candidates.get(name, ())
    if len(candidates) >= 2:
        return Reason.READERS_DISAGREE, "multi_rating", " | ".join(candidates), True
    return None


def decide_field(
    name: str, reading: FieldReading, evidence: OcrEvidence, photo_ref: str,
    anchored: frozenset[str] = frozenset(IDENTIFIER_FIELDS),
) -> FieldDecision:
    """Apply the strict rule to one field; fields in `anchored` need their printed label (R5). Pure."""
    hint = evidence.hints.get(name)
    if reading.value is None:
        return field_stop(name, ReadStatus.UNREADABLE, Reason.MODEL_MISSING, "no_value", ocr_value=hint)
    attached = attach_power_unit(reading.value, reading.printed_label) if name == "power" else None
    value = attached or reading.value
    if not check_format(name, value):
        return field_stop(name, ReadStatus.UNREADABLE, Reason.FORMAT_FAIL, "format_rule", ocr_value=hint,
                     vision_value=reading.value, format_rule_passed=False)
    hit = locate(name, value, evidence.lines, min_height=evidence.min_box_height)
    if hit is None:
        return field_stop(name, ReadStatus.DISPUTED, Reason.NOT_LOCATED, "not_found", ocr_value=hint,
                     vision_value=reading.value, format_rule_passed=True)
    label = allowed_label(name, reading.printed_label)
    path = ocr_path(hit.pass_id)
    source = SourceRef(kind="photo_crop", ref_id=photo_ref, bbox=hit.bbox,
                       detail=f"field={name}; label={label or 'none'}; located_by={path}; pass={hit.pass_id}")
    if on_flagged_line(hit.bbox, evidence.flagged):
        return field_stop(name, ReadStatus.DISPUTED, Reason.READERS_DISAGREE, "injection_line", path, ocr_value=hit.ocr_text,
                     vision_value=reading.value, format_rule_passed=True, source=source, injection_flag=True)
    failed = _check_located(name, value, attached is not None, label, hit, hint, evidence, anchored)
    if failed is not None:
        reason, rule, ocr_value, keep = failed
        return field_stop(name, ReadStatus.DISPUTED, reason, rule, path if keep else None, ocr_value=ocr_value,
                     vision_value=reading.value, format_rule_passed=True, source=source if keep else None)
    field = ReadField(name=name, value=value, vision_value=reading.value, ocr_value=hit.ocr_text,
                      format_rule_passed=True, status=ReadStatus.READ, source=source)
    return FieldDecision(field, None, None, path)


Decider = Callable[[str, OcrEvidence, str], tuple[dict[str, FieldDecision], dict[str, str | None]]]


def _decide_nameplate(raw_text: str, evidence: OcrEvidence, photo_ref: str):
    try:
        readings = parse_labelled_reading(raw_text, NAMEPLATE_PROMPT.fields)
    except VisionError:
        # An unusable answer reads as "the model gave nothing", never as a crash or a guess.
        readings = {name: FieldReading(None, None) for name in NAMEPLATE_FIELDS}
    decisions = {name: decide_field(name, readings[name], evidence, photo_ref) for name in NAMEPLATE_FIELDS}
    warnings = {name: ("multi_row_table" if evidence.rating_table and name in MULTI_RATING_FIELDS else None)
                for name in NAMEPLATE_FIELDS}
    return decisions, warnings


def read_document(
    photo_path: Path, prompt: VisionPrompt, decide: Decider, observation_id: str | None = None,
    tag_read_ok: bool = False, *, vision: VisionReader | None = None, ocr: OcrRunner = run_rapidocr_and_tesseract,
    settings: Settings | None = None, fallback: VisionReader | None = None,
) -> NameplateRun:
    """Shared core: photo checks, one vision call, OCR evidence, the kind's field decisions, flagged lines."""
    photo_path = Path(photo_path)
    ensure_not_heldout(photo_path)
    if not photo_path.is_file():
        raise PerceptionError(f"photo not found: {photo_path}")
    from amber_lens.perception.providers import default_vision, fallback_vision, read_with_fallback

    if vision is None:
        settings = settings or load_settings()
        vision, fallback = default_vision(settings), fallback_vision(settings)
    # Vision and OCR are independent, so they run at the same time; the photo costs the slower of the two.
    with ThreadPoolExecutor(max_workers=2) as pool:
        call_job = pool.submit(read_with_fallback, vision, fallback, photo_path, prompt)
        ocr_job = pool.submit(_timed, ocr, photo_path)
        (call, failure), (ocr_result, ocr_ms) = call_job.result(), ocr_job.result()
    evidence = build_evidence(ocr_result)
    decisions, warnings = decide(call.raw_text if call else "{}", evidence, photo_path.name)
    if call is None:
        decisions = {name: field_stop(name, ReadStatus.DISPUTED, Reason.VISION_UNAVAILABLE, "vision_unavailable",
                                      ocr_value=d.field.ocr_value) for name, d in decisions.items()}
        warnings = {**warnings, "vision": f"vision_unavailable: {failure}"}
    call = call or VisionCall(vision.model, prompt.version, "", "", 0, 0, False)
    result = PerceptionResult(
        observation_id=observation_id or photo_path.stem,
        fields=[d.field for d in decisions.values()] + free_text_fields(evidence.flagged, photo_path.name),
        tag_read_ok=tag_read_ok,
        model_name=vision.model,
        latency_ms=max(call.latency_ms, ocr_ms),
        cost_usd=call.cost_usd,
    )
    return NameplateRun(
        result=result,
        reasons={name: (d.reason.value if d.reason else None) for name, d in decisions.items()},
        rules={name: d.rule for name, d in decisions.items()},
        located_by={name: d.located_by for name, d in decisions.items()},
        warnings=warnings,
        timings={"vision_ms": call.latency_ms, "ocr_ms": ocr_ms, "total_ms": max(call.latency_ms, ocr_ms),
                 "tokens": call.tokens},
    )


def _timed(ocr: OcrRunner, photo_path: Path) -> tuple[OcrResult, int]:
    started = time.perf_counter()
    result = ocr(photo_path)
    return result, int((time.perf_counter() - started) * 1000)


def run_nameplate(photo_path: Path, observation_id: str | None = None, tag_read_ok: bool = False,
                  **kwargs) -> NameplateRun:
    """Read one nameplate photo; returns the result plus the reason, rule and locating path of every field."""
    return read_document(photo_path, NAMEPLATE_PROMPT, _decide_nameplate, observation_id, tag_read_ok, **kwargs)


def read_nameplate(photo_path: Path, observation_id: str | None = None, **kwargs) -> PerceptionResult:
    """Photo in, PerceptionResult out. observation_id defaults to the file stem; no room tag is read here."""
    return run_nameplate(photo_path, observation_id, **kwargs).result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read one nameplate photo into a PerceptionResult")
    parser.add_argument("photo", type=Path)
    parser.add_argument("--observation-id", default=None)
    parser.add_argument("--out", type=Path, default=None, help="write the PerceptionResult JSON here")
    args = parser.parse_args(argv)
    run = run_nameplate(args.photo, args.observation_id)
    result_json = run.result.model_dump_json(indent=2)
    trace = json.dumps(
        {"reasons": run.reasons, "rules": run.rules, "located_by": run.located_by, "warnings": run.warnings}, indent=2
    )
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(result_json + "\n", encoding="utf-8")
        args.out.with_name(args.out.stem + "_reasons.json").write_text(trace + "\n", encoding="utf-8")
    print(result_json)
    print(trace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
