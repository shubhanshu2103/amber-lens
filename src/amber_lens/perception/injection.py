"""Flag label text that reads like an instruction to an AI (#12); flagged text is quoted evidence only."""

from __future__ import annotations

import re

from amber_lens.perception.locate import centre_inside, strict_key
from amber_lens.perception.ocr import OcrLine
from amber_lens.perception.rules import check_format, label_key
from amber_lens.perception.textfields import FIELD_PATTERNS
from amber_lens.schemas import BBox, ReadField, ReadStatus, SourceRef

# Fixed patterns only; a model never judges whether text is an instruction.
INSTRUCTION_PATTERNS = (
    r"\b(?:system|assistant|user)\s*:",
    r"\bignore\b.{0,30}\b(?:instructions?|previous|above|rules?)\b",
    r"\bnote to (?:the )?(?:receiver|inspector|reader|ai|system)\b",
    r"\b(?:mark|set|record|treat)\b.{0,40}\b(?:approved|accepted|complete|passed|verified|received)\b",
    r"\bskip\b.{0,20}\b(?:inspection|check|verification|review)\b",
    r"\b(?:do not|don't|never)\s+(?:inspect|check|verify|flag|report)\b",
    r"\byou (?:are|must|should|will)\b",
)
INSTRUCTION = re.compile("|".join(INSTRUCTION_PATTERNS), re.IGNORECASE)
MODEL_LABEL = FIELD_PATTERNS["model_number"][0]


def looks_like_instruction(text: str) -> bool:
    return INSTRUCTION.search(" ".join(text.split())) is not None


def _second_model_labels(lines: list[OcrLine]) -> list[OcrLine]:
    """Lines repeating the same printed MODEL label with another value: a planted second label."""
    by_label: dict[str, list[tuple[str, OcrLine]]] = {}
    for line in lines:
        for m in MODEL_LABEL.finditer(line.text.upper()):
            if check_format("model_number", m.group("v")):
                label = label_key(m.group(0)[: m.start("v") - m.start()])
                by_label.setdefault(label, []).append((strict_key("model_number", m.group("v")), line))
    return [line for found in by_label.values() if len({key for key, _ in found}) >= 2 for _, line in found]


def flagged_lines(lines: tuple[OcrLine, ...], primary_pass: str) -> list[OcrLine]:
    """Instruction-like lines plus planted second MODEL labels, one per printed line across OCR passes."""
    primary = [line for line in lines if line.pass_id == primary_pass]
    kept: list[OcrLine] = []
    for line in [line for line in lines if looks_like_instruction(line.text)] + _second_model_labels(primary):
        if not any(centre_inside(line.bbox, other.bbox) for other in kept):
            kept.append(line)
    return kept


def on_flagged_line(box: BBox, flagged: list[OcrLine]) -> bool:
    return any(centre_inside(box, line.bbox) for line in flagged)


def free_text_fields(flagged: list[OcrLine], photo_ref: str) -> list[ReadField]:
    """One DISPUTED free_text_n field per flagged line: value None, the text kept only as quoted evidence."""
    return [
        ReadField(name=f"free_text_{i}", value=None, ocr_value=line.text, status=ReadStatus.DISPUTED,
                  injection_flag=True, source=SourceRef(kind="photo_crop", ref_id=photo_ref, bbox=line.bbox,
                                                        detail="injection_flag; quoted evidence only"))
        for i, line in enumerate(flagged, 1)
    ]
