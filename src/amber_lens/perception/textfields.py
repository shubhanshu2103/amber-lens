"""Pull nameplate fields out of OCR lines with fixed label patterns.

This is the OCR-only reading of a plate. It is used as the OCR arm of the spike and, in the reader,
as the independent second opinion that can contradict the vision model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from amber_lens.perception.ocr import OcrLine

_VALUE = r"(?P<v>[A-Z0-9][A-Z0-9\-./]{2,})"
_VOLTS = r"(?P<v>\d{2,4}(?:\s*[/\-]\s*\d{2,4})*)"
_AMPS = r"(?P<v>\d+(?:[.,]\d+)?(?:\s*[/\-]\s*\d+(?:[.,]\d+)?)*)"
_POWER = r"(?P<v>(?:\d+\s+)?\d+(?:[.,/]\d+)?)"

# Ordered patterns per field; the first match in reading order wins.
FIELD_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "catalog_number": (
        re.compile(r"\bCAT(?:ALOGUE|ALOG)?\.?\s*(?:NO|NUMBER|#)\.?\s*[:#]?\s*" + _VALUE),
        re.compile(r"\bORD(?:ER)?\.?\s*(?:NO|NR|NUMBER)\.?\s*[:#]?\s*" + _VALUE),
    ),
    "model_number": (
        re.compile(r"\bMOD(?:EL)?\.?\s*(?:NO|NUMBER|#)?\.?\s*[:#]?\s*" + _VALUE),
        re.compile(r"\bTYPE\s*[:#]?\s*" + _VALUE),
    ),
    "voltage": (
        re.compile(r"\bVOLTS?\.?\s*[:]?\s*" + _VOLTS),
        re.compile(_VOLTS + r"\s*V\b"),
    ),
    "rated_current": (
        re.compile(r"\b(?:AMPS?|F\.?L\.?A|RLA|CURRENT)\.?\s*[:]?\s*" + _AMPS),
        re.compile(_AMPS + r"\s*A\b"),
    ),
    "power": (
        re.compile(_POWER + r"\s*(?P<u>HP|KW|KVA)\b"),
        re.compile(r"\b(?P<u>HP|KW|KVA)\.?\s*[:]?\s*" + _POWER),
    ),
    "frequency": (
        re.compile(r"\b(?:HZ|HERTZ|CYCLES)\.?\s*[:]?\s*(?P<v>\d{2,3}(?:\s*/\s*\d{2,3})?)"),
        re.compile(r"(?P<v>\d{2,3}(?:\s*/\s*\d{2,3})?)\s*HZ\b"),
        re.compile(r"(?P<v>\d{2,3})\s*CYCLES?\b"),
    ),
}


@dataclass(frozen=True)
class TextHit:
    value: str
    line_index: int


def _format_hit(field: str, match: re.Match[str]) -> str:
    value = " ".join(match.group("v").split())
    if field == "power":
        return f"{value} {match.group('u')}"
    return value


def extract_fields(lines: tuple[OcrLine, ...] | list[OcrLine]) -> dict[str, TextHit | None]:
    """Field -> first pattern hit across lines (pattern priority first, then reading order)."""
    upper = [line.text.upper() for line in lines]
    hits: dict[str, TextHit | None] = {}
    for field, patterns in FIELD_PATTERNS.items():
        hits[field] = None
        for pattern in patterns:
            found = next(
                ((i, m) for i, text in enumerate(upper) if (m := pattern.search(text)) is not None),
                None,
            )
            if found is not None:
                index, match = found
                hits[field] = TextHit(value=_format_hit(field, match), line_index=index)
                break
    return hits


def all_values(field: str, lines: tuple[OcrLine, ...] | list[OcrLine]) -> list[str]:
    """Every value the field's patterns find on any line, in pattern then reading order (rule R4 input)."""
    return [
        _format_hit(field, match)
        for pattern in FIELD_PATTERNS[field]
        for line in lines
        for match in pattern.finditer(line.text.upper())
    ]
