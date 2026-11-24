"""Find where a read value is printed on the photo, using OCR word boxes.

A value is located when a run of OCR words on one line spells the value's core (the value without its
unit words and labeller-style annotations). Characters OCR commonly confuses (O/0, I/1, S/5, B/8, Z/2)
are folded to find the box, so one misread glyph does not hide where the value is printed. Whether OCR
read the same characters is reported separately as `exact`; the reader treats a non-exact hit as the
two readers disagreeing. The value itself is never changed here.
"""

from __future__ import annotations

import re
import statistics
import unicodedata
from dataclasses import dataclass

from amber_lens.perception.ocr import OcrLine, union_bbox
from amber_lens.perception.rules import PRINTED_LABELS, label_key
from amber_lens.schemas import BBox

MAX_SPAN_WORDS = 6
# A rating core this short ("15", "60") is too common to trust without its unit or label on the same line.
SHORT_CORE_LEN = 3
RATING_FIELDS = frozenset({"voltage", "rated_current", "power", "frequency"})
# Rule R2: a located box shorter than this, or than 60% of the photo's median OCR line height, is noise.
MIN_BOX_HEIGHT_PX = 8
MIN_BOX_HEIGHT_SHARE = 0.6
# Rule R5 geometry: a label to the left on the same row within this many value heights, or directly above.
LABEL_LEFT_GAP_HEIGHTS = 8
LABEL_ABOVE_GAP_HEIGHTS = 2

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—−"), "-")
_CONFUSABLE = str.maketrans({"o": "0", "i": "1", "l": "1", "|": "1", "s": "5", "b": "8", "z": "2"})
_UNIT_WORDS: dict[str, re.Pattern[str]] = {
    "voltage": re.compile(r"(?<![a-z])(?:volts?|vac|v)(?![a-z])"),
    "rated_current": re.compile(r"(?<![a-z])(?:amps?|fla|rla|a)(?![a-z])"),
    "frequency": re.compile(r"(?<![a-z])(?:hz|hertz|cycles)(?![a-z])"),
    "power": re.compile(r"(?<![a-z])(?:hp|kw|kva|va|w)(?![a-z])"),
}
_EDGE_PUNCT = ".,:;#()[]"
_JOINERS = "-/‐‑‒–—−"


@dataclass(frozen=True)
class LocateHit:
    bbox: BBox
    ocr_text: str
    pass_id: str
    # True when OCR read exactly the same characters (case, spacing, dash style and units aside).
    exact: bool
    # Rule R1: the matched words continue into a neighbouring word through a dash or slash.
    fragment: bool
    # Where the (first) matched part sits, for adjacency checks.
    line: OcrLine
    start: int
    end: int


def match_key(text: str, fold: bool = True) -> str:
    """Comparison form: NFKC, lower case, one dash style, decimal point, no spaces; confusables folded if asked."""
    text = unicodedata.normalize("NFKC", text).casefold().translate(_DASHES)
    text = re.sub(r"(?<=\d),(?=\d)", ".", text)
    text = re.sub(r"\s+", "", text)
    return text.translate(_CONFUSABLE) if fold else text


def _strip_units(field: str, text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"\([^()\d]*\)", " ", text)
    return _UNIT_WORDS[field].sub(" ", text) if field in _UNIT_WORDS else text


def _split_parts(field: str, text: str) -> list[str]:
    # "480 V / 400 V" is two printed ratings; "230/460" with no spaces is one printed token.
    if field not in RATING_FIELDS:
        return [text]
    return [p for p in re.split(r"\s/\s", text) if p.strip()]


def value_parts(field: str, value: str, fold: bool = True) -> list[str]:
    """The printed cores to look for: unit words and word-only annotations removed, split on ' / '."""
    parts = _split_parts(field, _strip_units(field, value))
    return [key for p in parts if (key := match_key(p, fold).strip(_EDGE_PUNCT))]


def strict_key(field: str, value: str) -> str:
    """Unfolded comparison key of a whole value, used to decide whether two readers agree."""
    return "/".join(value_parts(field, value, fold=False))


def min_box_height(lines: tuple[OcrLine, ...] | list[OcrLine]) -> float:
    """Rule R2 threshold for one photo: at least 8 px and at least 60% of the median OCR line height."""
    if not lines:
        return float(MIN_BOX_HEIGHT_PX)
    return max(float(MIN_BOX_HEIGHT_PX), MIN_BOX_HEIGHT_SHARE * statistics.median(line.bbox.h for line in lines))


def _word_key(field: str, text: str, fold: bool) -> str:
    # A slash glued to the end ("ALPHA-0412/") is not part of the value; is_fragment decides what it joins.
    return match_key(_strip_units(field, text), fold).strip(_EDGE_PUNCT).rstrip("/")


def _span_matches(span_key: str, target: str, raw_span: str, single_word: bool) -> bool:
    """span_key and target are compared as given; a glued label prefix is judged on the unfolded raw_span.

    Folding maps one character to one character, so the prefix has the same length in both forms. A label
    glued to the value inside one OCR token ("amp.7.8/3.9" for "7.8/3.9") passes; a prefix holding other
    digits never does, and across several words the span must equal the value exactly.
    """
    if span_key == target:
        return True
    if single_word and span_key.endswith(target):
        prefix = raw_span[: len(raw_span) - len(target)]
        return re.fullmatch(r"[a-z.:#]*[.:#]", prefix) is not None
    return False


def _has_unit_context(field: str, line: OcrLine) -> bool:
    return field in _UNIT_WORDS and _UNIT_WORDS[field].search(line.text.casefold()) is not None


def is_fragment(line: OcrLine, start: int, end: int, multi_part: bool) -> bool:
    """Rule R1: the value continues into a neighbour through a dash or slash ("13ACD" "-036", "230/" "460")."""
    words = line.words
    following = words[end + 1].text if end + 1 < len(words) else ""
    # Between the parts of "480 V / 400 V" a lone "/" is the expected separator, not a continuation.
    if following and following[0] in _JOINERS and not (multi_part and following == "/"):
        return True
    # A slash glued to the end joins only a following number; "ALPHA-0412/" "Line" is a separator.
    if words[end].text.strip(_EDGE_PUNCT).endswith("/") and following[:1].isdigit():
        return True
    return start > 0 and words[start - 1].text[-1:] in _JOINERS


def _locate_part(
    field: str, target: str, exact_target: str, lines: tuple[OcrLine, ...] | list[OcrLine],
    min_height: float, multi_part: bool,
) -> LocateHit | None:
    needs_context = field in RATING_FIELDS and len(target) <= SHORT_CORE_LEN
    for line in lines:
        if needs_context and not _has_unit_context(field, line):
            continue
        keys = [_word_key(field, w.text, fold=True) for w in line.words]
        raw_keys = [_word_key(field, w.text, fold=False) for w in line.words]
        for start in range(len(keys)):
            # A span never starts on a word that is only a label or unit, so the box stays tight.
            if not keys[start]:
                continue
            span = raw_span = ""
            for end in range(start, min(start + MAX_SPAN_WORDS, len(keys))):
                span += keys[end]
                raw_span += raw_keys[end]
                if _span_matches(span, target, raw_span, single_word=end == start):
                    words = line.words[start : end + 1]
                    bbox = union_bbox([w.bbox for w in words])
                    if bbox.h < min_height:
                        break
                    return LocateHit(
                        bbox=bbox,
                        ocr_text=" ".join(w.text for w in words),
                        pass_id=line.pass_id,
                        exact=_span_matches(raw_span, exact_target, raw_span, single_word=end == start),
                        fragment=is_fragment(line, start, end, multi_part),
                        line=line,
                        start=start,
                        end=end,
                    )
                if len(span) > len(target) + 12:
                    break
    return None


def locate(
    field: str, value: str, lines: tuple[OcrLine, ...] | list[OcrLine], min_height: float = 0.0
) -> LocateHit | None:
    """Hit covering every printed part of the value, or None if any part cannot be found."""
    folded = value_parts(field, value, fold=True)
    exact = value_parts(field, value, fold=False)
    if not folded or len(folded) != len(exact):
        return None
    multi_part = len(folded) > 1
    hits = []
    for target, exact_target in zip(folded, exact, strict=True):
        hit = _locate_part(field, target, exact_target, lines, min_height, multi_part)
        if hit is None:
            return None
        hits.append(hit)
    first = hits[0]
    return LocateHit(
        bbox=union_bbox([h.bbox for h in hits]),
        ocr_text=" / ".join(h.ocr_text for h in hits),
        pass_id=first.pass_id,
        exact=all(h.exact for h in hits),
        fragment=any(h.fragment for h in hits),
        line=first.line,
        start=first.start,
        end=first.end,
    )


def _left_on_row(label: BBox, value: BBox) -> bool:
    label_mid = label.y + label.h / 2
    same_row = value.y - value.h / 2 <= label_mid <= value.y + value.h * 1.5
    gap = value.x - (label.x + label.w)
    return same_row and -2 <= gap <= LABEL_LEFT_GAP_HEIGHTS * value.h


def _directly_above(label: BBox, value: BBox) -> bool:
    gap = value.y - (label.y + label.h)
    overlaps = label.x < value.x + value.w and value.x < label.x + label.w
    return overlaps and -2 <= gap <= LABEL_ABOVE_GAP_HEIGHTS * value.h


def _glued_label(word_text: str, labels: frozenset[str]) -> bool:
    # A label glued in front of the value inside one token, ending in '.', ':' or '#' ("CAT.NO.HHI150").
    match = re.match(r"([A-Za-z][A-Za-z.\s]*[.:#])", word_text)
    return match is not None and label_key(match.group(1)) in labels


def has_label_anchor(field: str, hit: LocateHit, lines: tuple[OcrLine, ...] | list[OcrLine]) -> bool:
    """Rule R5: OCR finds the field's own printed label left of the value on its row, or directly above it."""
    labels = PRINTED_LABELS[field]
    if _glued_label(hit.line.words[hit.start].text, labels):
        return True
    return any(_left_on_row(box, hit.bbox) or _directly_above(box, hit.bbox) for box in label_boxes(lines, labels))


def label_boxes(lines: tuple[OcrLine, ...] | list[OcrLine], labels: frozenset[str] | set[str]) -> list[BBox]:
    """Boxes of every run of 1-3 OCR words on a line that spells one of the labels."""
    boxes = []
    for line in lines:
        words = line.words
        for i in range(len(words)):
            for j in range(i, min(i + 3, len(words))):
                if label_key(" ".join(w.text for w in words[i : j + 1])) in labels:
                    boxes.append(union_bbox([w.bbox for w in words[i : j + 1]]))
    return boxes


def unit_adjacent(hit: LocateHit, unit_label: str) -> bool:
    """T2-8: the located number has its unit label as the word directly before or after it, or glued to it."""
    unit = label_key(unit_label)
    words = hit.line.words
    neighbours = [words[i].text for i in (hit.start - 1, hit.end + 1) if 0 <= i < len(words)]
    if any(label_key(text).strip(_EDGE_PUNCT.upper()) == unit for text in neighbours):
        return True
    own = label_key(" ".join(w.text for w in words[hit.start : hit.end + 1]))
    return re.fullmatch(rf"(?:{unit}[\d.,/]+|[\d.,/]+{unit})", own) is not None


TABLE_HEADERS = frozenset({"V", "HZ", "A", "KW", "HP"})


def has_rating_table(lines: tuple[OcrLine, ...] | list[OcrLine]) -> bool:
    """R6 detector (warning only): a row of 2+ unit headers with 2+ rows of numbers under one of them."""
    headers = [(label_key(w.text), w.bbox) for line in lines for w in line.words if label_key(w.text) in TABLE_HEADERS]
    numbers = [w.bbox for line in lines for w in line.words if re.fullmatch(r"[\d.,/]+", w.text)]
    for _, box in headers:
        mid = box.y + box.h / 2
        if len({k for k, b in headers if abs(b.y + b.h / 2 - mid) <= box.h / 2}) < 2:
            continue
        rows = {round((b.y - box.y) / box.h) for b in numbers
                if box.y + box.h <= b.y <= box.y + 8 * box.h and abs(b.x - box.x) <= 3 * box.h}
        if len(rows) >= 2:
            return True
    return False


def centre_inside(box: BBox, other: BBox) -> bool:
    """The centre of box lies inside other."""
    cx, cy = box.x + box.w / 2, box.y + box.h / 2
    return other.x <= cx <= other.x + other.w and other.y <= cy <= other.y + other.h
