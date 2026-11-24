"""Nameplate reader: photo in, PerceptionResult out (#11).

A field is READ only when every check passes, in this order (failing check -> reason):
  1. the vision model gave a value                                       model_missing
  2. (a bare power number takes its printed unit label: HP, kW, kVA)
  3. the value passes its format rule; a rating holds only its unit words (R3)   format_fail
  4. OCR finds it on the photo, box >= 8 px and 60% of the median line (R2)       not_located
  5. not a fragment of a longer dash- or slash-joined token (R1)          readers_disagree
  6. OCR read the same characters                                         readers_disagree
  7. an attached power unit sits directly next to the number              not_located
  8. an identifier has its printed label left of it or above it (R5)      not_located
  9. OCR's reading under the field's label gives no other value           readers_disagree
 10. voltage / current / frequency: no 2+ different values on the plate (R4)   readers_disagree
A value OCR finds on a flagged line (instruction-like text, or a second MODEL label with another value)
is never READ: DISPUTED, readers_disagree, injection_flag=True (#12). Each flagged line is also added as a
DISPUTED free_text_n field with value None; its text is quoted evidence only and never enters a prompt.
Failures are UNREADABLE (model_missing, format_fail) or DISPUTED (others) with value None. OCR never makes
a field READ on its own; the model's own confidence is never used.

run_nameplate returns, from the same run: result (PerceptionResult), reasons (None = READ), rules (the
exact check that stopped each field), located_by (rapidocr / full_ocr / crop_ocr) and warnings.
Warning "multi_row_table" (R6): voltage, current and frequency on a plate with a row of unit headers and
several rows of values under them; it never changes a status. read_nameplate returns only the result.

How to run:
    python -m amber_lens.perception.reader <photo> --out examples/perception_result_sample.json
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from amber_lens.perception.cache import ResponseCache
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
    OllamaVision,
    VisionCall,
    VisionError,
    VisionPrompt,
    parse_labelled_reading,
)
from amber_lens.schemas import Observation, PerceptionResult, ReadField, ReadStatus, SourceRef

FULL_OCR = "full_ocr"
RAPIDOCR = "rapidocr"
CROP_OCR = "crop_ocr"
MULTI_RATING_FIELDS = ("voltage", "rated_current", "frequency")


class Reason(str, Enum):
    FORMAT_FAIL = "format_fail"
    READERS_DISAGREE = "readers_disagree"
    NOT_LOCATED = "not_located"
    MODEL_MISSING = "model_missing"


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


def _path(pass_id: str) -> str:
    if pass_id == RAPID_PASS:
        return RAPIDOCR
    return CROP_OCR if pass_id == CROP_PASS else FULL_OCR


def _stop(name: str, status: ReadStatus, reason: Reason, rule: str, located_by: str | None = None,
          **fields) -> FieldDecision:
    return FieldDecision(ReadField(name=name, value=None, status=status, **fields), reason, rule, located_by)


def _check_located(
    name: str, value: str, attached: bool, label: str | None, hit: LocateHit, hint: str | None, evidence: OcrEvidence
) -> tuple[Reason, str, str | None, bool] | None:
    """Checks after the value is found: (reason, rule, ocr_value, keep the source) for the first that fails."""
    if hit.fragment:
        return Reason.READERS_DISAGREE, "fragment", hit.ocr_text, True
    if not hit.exact:
        return Reason.READERS_DISAGREE, "glyph_mismatch", hit.ocr_text, True
    if attached and not unit_adjacent(hit, label or ""):
        return Reason.NOT_LOCATED, "unit_not_adjacent", hit.ocr_text, False
    if name in IDENTIFIER_FIELDS and not has_label_anchor(name, hit, evidence.lines):
        return Reason.NOT_LOCATED, "label_anchor_missing", hit.ocr_text, False
    if hint is not None and check_format(name, hint) and strict_key(name, hint) != strict_key(name, value):
        return Reason.READERS_DISAGREE, "ocr_label_value_differs", hint, True
    candidates = evidence.candidates.get(name, ())
    if len(candidates) >= 2:
        return Reason.READERS_DISAGREE, "multi_rating", " | ".join(candidates), True
    return None


def decide_field(name: str, reading: FieldReading, evidence: OcrEvidence, photo_ref: str) -> FieldDecision:
    """Apply the strict rule to one field. Pure: same inputs, same decision."""
    hint = evidence.hints.get(name)
    if reading.value is None:
        return _stop(name, ReadStatus.UNREADABLE, Reason.MODEL_MISSING, "no_value", ocr_value=hint)
    attached = attach_power_unit(reading.value, reading.printed_label) if name == "power" else None
    value = attached or reading.value
    if not check_format(name, value):
        return _stop(name, ReadStatus.UNREADABLE, Reason.FORMAT_FAIL, "format_rule", ocr_value=hint,
                     vision_value=reading.value, format_rule_passed=False)
    hit = locate(name, value, evidence.lines, min_height=evidence.min_box_height)
    if hit is None:
        return _stop(name, ReadStatus.DISPUTED, Reason.NOT_LOCATED, "not_found", ocr_value=hint,
                     vision_value=reading.value, format_rule_passed=True)
    label = allowed_label(name, reading.printed_label)
    path = _path(hit.pass_id)
    source = SourceRef(kind="photo_crop", ref_id=photo_ref, bbox=hit.bbox,
                       detail=f"field={name}; label={label or 'none'}; located_by={path}; pass={hit.pass_id}")
    if on_flagged_line(hit.bbox, evidence.flagged):
        return _stop(name, ReadStatus.DISPUTED, Reason.READERS_DISAGREE, "injection_line", path, ocr_value=hit.ocr_text,
                     vision_value=reading.value, format_rule_passed=True, source=source, injection_flag=True)
    failed = _check_located(name, value, attached is not None, label, hit, hint, evidence)
    if failed is not None:
        reason, rule, ocr_value, keep = failed
        return _stop(name, ReadStatus.DISPUTED, reason, rule, path if keep else None, ocr_value=ocr_value,
                     vision_value=reading.value, format_rule_passed=True, source=source if keep else None)
    field = ReadField(name=name, value=value, vision_value=reading.value, ocr_value=hit.ocr_text,
                      format_rule_passed=True, status=ReadStatus.READ, source=source)
    return FieldDecision(field, None, None, path)


def _readings(call: VisionCall) -> dict[str, FieldReading]:
    try:
        return parse_labelled_reading(call.raw_text, NAMEPLATE_PROMPT.fields)
    except VisionError:
        # An unusable answer reads as "the model gave nothing", never as a crash or a guess.
        return {name: FieldReading(None, None) for name in NAMEPLATE_PROMPT.fields}


def default_vision(settings: Settings) -> OllamaVision:
    return OllamaVision(settings.ollama_host, settings.vision_model, ResponseCache(settings.cache_dir / "vision"))


def run_nameplate(
    photo_path: Path,
    observation_id: str | None = None,
    tag_read_ok: bool = False,
    *,
    vision: VisionReader | None = None,
    ocr: OcrRunner = run_rapidocr_and_tesseract,
    settings: Settings | None = None,
) -> NameplateRun:
    """Read one nameplate photo; returns the result plus the reason, rule and locating path of every field."""
    photo_path = Path(photo_path)
    ensure_not_heldout(photo_path)
    if not photo_path.is_file():
        raise PerceptionError(f"photo not found: {photo_path}")
    if vision is None:
        vision = default_vision(settings or load_settings())
    call = vision.read(photo_path, NAMEPLATE_PROMPT)
    readings = _readings(call)
    ocr_result = ocr(photo_path)
    evidence = build_evidence(ocr_result)
    decisions = {name: decide_field(name, readings[name], evidence, photo_path.name) for name in NAMEPLATE_FIELDS}
    result = PerceptionResult(
        observation_id=observation_id or photo_path.stem,
        fields=[d.field for d in decisions.values()] + free_text_fields(evidence.flagged, photo_path.name),
        tag_read_ok=tag_read_ok,
        model_name=vision.model,
        latency_ms=call.latency_ms + ocr_result.latency_ms,
        cost_usd=0.0,
    )
    return NameplateRun(
        result=result,
        reasons={name: (d.reason.value if d.reason else None) for name, d in decisions.items()},
        rules={name: d.rule for name, d in decisions.items()},
        located_by={name: d.located_by for name, d in decisions.items()},
        warnings={name: ("multi_row_table" if evidence.rating_table and name in MULTI_RATING_FIELDS else None)
                  for name in NAMEPLATE_FIELDS},
    )


def read_nameplate(photo_path: Path, observation_id: str | None = None, **kwargs) -> PerceptionResult:
    """Photo in, PerceptionResult out. observation_id defaults to the file stem; no room tag is read here."""
    return run_nameplate(photo_path, observation_id, **kwargs).result


def read_observation(observation: Observation, **kwargs) -> PerceptionResult:
    """Read a captured nameplate; tag_read_ok only when the capture decoded the room tag from a QR code."""
    if observation.kind != "nameplate":
        raise PerceptionError(f"reading {observation.kind} photos is not supported yet")
    photo = Path(observation.photo_path)
    sidecar = photo.with_suffix(".json")
    source = json.loads(sidecar.read_text(encoding="utf-8")).get("room_tag_source") if sidecar.is_file() else None
    tag_ok = observation.room_tag is not None and source in ("qr_in_photo", "qr_photo")
    return run_nameplate(photo, observation.observation_id, tag_read_ok=tag_ok, **kwargs).result


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
