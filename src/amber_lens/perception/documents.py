"""Crate labels and delivery tickets (#22), and read_observation for every captured kind.

Crate label fields (model_number, qty, po_number, po_line) follow the nameplate rule, and each needs its
printed label left of it or directly above (R5); so do a ticket's po_number and delivery_ticket_id.
A ticket line's cell is READ only from exactly one OCR word that equals the vision value exactly (no glyph
folding), sits under its column header (Model, Qty, Line) and, for qty and po_line, on the same printed row
as the line's model number (vertical overlap at least 50% of the shorter box). No such word: not_located;
two or more: readers_disagree (ambiguous). A line whose model number is not READ has no READ cells.
Warning "line_count_mismatch" (key "lines") when the model reports a different number of lines than OCR
finds model numbers under the Model column.
"""

from __future__ import annotations

import json
from pathlib import Path

from amber_lens.perception.injection import on_flagged_line
from amber_lens.perception.locate import centre_inside, is_fragment, label_boxes, strict_key
from amber_lens.perception.ocr import OcrLine
from amber_lens.perception.reader import (
    FieldDecision,
    NameplateRun,
    OcrEvidence,
    PerceptionError,
    Reason,
    decide_field,
    field_stop,
    ocr_path,
    read_document,
    run_nameplate,
)
from amber_lens.perception.rules import PRINTED_LABELS, check_format
from amber_lens.perception.vision import (
    CRATE_PROMPT,
    TICKET_PROMPT,
    FieldReading,
    VisionError,
    clean_string,
    load_object,
    parse_labelled_reading,
)
from amber_lens.schemas import BBox, Observation, PerceptionResult, ReadField, ReadStatus, SourceRef

CRATE_FIELDS = CRATE_PROMPT.fields
TICKET_HEADER = ("po_number", "delivery_ticket_id")
MAX_LINES = 50


def same_row(a: BBox, b: BBox) -> bool:
    return min(a.y + a.h, b.y + b.h) - max(a.y, b.y) >= 0.5 * min(a.h, b.h)


def _under(box: BBox, header: BBox) -> bool:
    centre_y = box.y + box.h / 2
    return header.y + header.h <= centre_y and box.x < header.x + header.w and header.x < box.x + box.w


def _column(field: str, evidence: OcrEvidence) -> list[tuple[OcrLine, int]]:
    headers = label_boxes(evidence.lines, PRINTED_LABELS[field])
    return [(line, i) for line in evidence.lines for i, word in enumerate(line.words)
            if any(_under(word.bbox, header) for header in headers)]


def _distinct(found: list[tuple[OcrLine, int]]) -> list[tuple[OcrLine, int]]:
    """One entry per printed position: the same word read by several OCR passes counts once."""
    kept: list[tuple[OcrLine, int]] = []
    for line, i in found:
        if not any(centre_inside(line.words[i].bbox, other.words[j].bbox) for other, j in kept):
            kept.append((line, i))
    return kept


def decide_cell(name: str, field: str, value: str | None, evidence: OcrEvidence, row: BBox | None,
                photo_ref: str) -> FieldDecision:
    """One table cell: exactly one exact OCR word under the column header, on `row` when given."""
    if value is None:
        return field_stop(name, ReadStatus.UNREADABLE, Reason.MODEL_MISSING, "no_value")
    if not check_format(field, value):
        return field_stop(name, ReadStatus.UNREADABLE, Reason.FORMAT_FAIL, "format_rule", vision_value=value,
                          format_rule_passed=False)
    key = strict_key(field, value)
    found = _distinct([(line, i) for line, i in _column(field, evidence) if strict_key(field, line.words[i].text) == key
                       and (row is None or same_row(line.words[i].bbox, row))])
    if len(found) != 1:
        reason, rule = (Reason.NOT_LOCATED, "cell_not_found") if not found else (Reason.READERS_DISAGREE, "ambiguous_cell")
        return field_stop(name, ReadStatus.DISPUTED, reason, rule, vision_value=value, format_rule_passed=True)
    line, i = found[0]
    word, path = line.words[i], ocr_path(line.pass_id)
    source = SourceRef(kind="photo_crop", ref_id=photo_ref, bbox=word.bbox,
                       detail=f"field={name}; label=column; located_by={path}; pass={line.pass_id}")
    common = {"vision_value": value, "ocr_value": word.text, "format_rule_passed": True, "source": source}
    if on_flagged_line(word.bbox, evidence.flagged):
        return field_stop(name, ReadStatus.DISPUTED, Reason.READERS_DISAGREE, "injection_line", path,
                          injection_flag=True, **common)
    if is_fragment(line, i, i, False):
        return field_stop(name, ReadStatus.DISPUTED, Reason.READERS_DISAGREE, "fragment", path, **common)
    return FieldDecision(ReadField(name=name, value=value, status=ReadStatus.READ, **common), None, None, path)


def _decide_crate(raw_text: str, evidence: OcrEvidence, photo_ref: str):
    try:
        readings = parse_labelled_reading(raw_text, CRATE_FIELDS)
    except VisionError:
        readings = {name: FieldReading(None, None) for name in CRATE_FIELDS}
    anchored = frozenset(CRATE_FIELDS)
    return {name: decide_field(name, readings[name], evidence, photo_ref, anchored) for name in CRATE_FIELDS}, {}


def _decide_ticket(raw_text: str, evidence: OcrEvidence, photo_ref: str):
    try:
        data = load_object(raw_text)
    except VisionError:
        data = {}
    anchored = frozenset(TICKET_HEADER)
    decisions = {name: decide_field(name, FieldReading(clean_string(data.get(name)), None), evidence, photo_ref,
                                    anchored) for name in TICKET_HEADER}
    rows = [row for row in data.get("lines") or [] if isinstance(row, dict)][:MAX_LINES]
    for n, row in enumerate(rows, 1):
        model = decide_cell(f"line[{n}].model_number", "model_number", clean_string(row.get("model_number")),
                            evidence, None, photo_ref)
        decisions[model.field.name] = model
        anchor = model.field.source.bbox if model.field.status is ReadStatus.READ else None
        for field in ("qty", "po_line"):
            name, value = f"line[{n}].{field}", clean_string(row.get(field))
            if anchor is None and value is not None:
                decisions[name] = field_stop(name, ReadStatus.DISPUTED, Reason.NOT_LOCATED, "line_model_not_read",
                                             vision_value=value)
            else:
                decisions[name] = decide_cell(name, field, value, evidence, anchor, photo_ref)
    models = _distinct([(line, i) for line, i in _column("model_number", evidence)
                        if check_format("model_number", line.words[i].text)])
    return decisions, {"lines": "line_count_mismatch" if len(models) != len(rows) else None}


def read_crate_label(photo_path: Path, observation_id: str | None = None, tag_read_ok: bool = False,
                     **kwargs) -> NameplateRun:
    return read_document(photo_path, CRATE_PROMPT, _decide_crate, observation_id, tag_read_ok, **kwargs)


def read_delivery_ticket(photo_path: Path, observation_id: str | None = None, tag_read_ok: bool = False,
                         **kwargs) -> NameplateRun:
    return read_document(photo_path, TICKET_PROMPT, _decide_ticket, observation_id, tag_read_ok, **kwargs)


READERS = {"nameplate": run_nameplate, "crate_label": read_crate_label, "delivery_ticket": read_delivery_ticket}


def read_observation(observation: Observation, **kwargs) -> PerceptionResult:
    """Read a capture by its kind; tag_read_ok only when the capture decoded the room tag from a QR code."""
    reader = READERS.get(observation.kind)
    if reader is None:
        raise PerceptionError(f"reading {observation.kind} photos is not supported yet")
    photo = Path(observation.photo_path)
    sidecar = photo.with_suffix(".json")
    source = json.loads(sidecar.read_text(encoding="utf-8")).get("room_tag_source") if sidecar.is_file() else None
    tag_ok = observation.room_tag is not None and source in ("qr_in_photo", "qr_photo")
    return reader(photo, observation.observation_id, tag_read_ok=tag_ok, **kwargs).result
