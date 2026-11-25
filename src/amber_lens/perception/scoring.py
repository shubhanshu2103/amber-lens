"""Compare read values with labels.csv. Used only for measurement, never inside the reader.

Values are compared on a key that ignores case, whitespace, dash style, decimal comma vs point, the
field's own unit words and word-only annotations added by the labeller, e.g. "(compressor RLA)".
Digits, separators and other units stay significant.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from enum import Enum

_WORD_PARENS = re.compile(r"\([^()\d]*\)")
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—−"), "-")
_UNIT_WORDS: dict[str, re.Pattern[str]] = {
    "voltage": re.compile(r"(?<![a-z])(?:volts?|vac|v)(?![a-z])"),
    "rated_current": re.compile(r"(?<![a-z])(?:amps?|a)(?![a-z])"),
    "frequency": re.compile(r"(?<![a-z])(?:hz|hertz|cycles)(?![a-z])"),
}


class Outcome(str, Enum):
    """correct: value matches the label. wrong: value given, label differs. extra: value given, label says
    the plate does not print it. missed: no value, label has one. abstained_ok: no value, label has none."""

    CORRECT = "correct"
    WRONG = "wrong"
    EXTRA = "extra"
    MISSED = "missed"
    ABSTAINED_OK = "abstained_ok"


WRONG_OUTCOMES = frozenset({Outcome.WRONG, Outcome.EXTRA})


def comparison_key(field: str, value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold().translate(_DASHES)
    # Agreement is on the value, not typography: a decimal comma reads the same as a decimal point.
    text = re.sub(r"(?<=\d),(?=\d)", ".", text)
    text = _WORD_PARENS.sub(" ", text)
    if field in _UNIT_WORDS:
        text = _UNIT_WORDS[field].sub(" ", text)
    if field == "manufacturer":
        return re.sub(r"[^0-9a-z]", "", text)
    # Punctuation left behind by a removed unit word ("7.8/3.9 AMP.") is not part of the value.
    return re.sub(r"\s+", "", text).strip(".,:;")


def _truth_keys(field: str, truth: str) -> set[str]:
    """The full label plus each part split on parentheses, so '1.0 HP (0.75 kW)' accepts '1.0 HP'."""
    keys = {comparison_key(field, truth)}
    keys.update(comparison_key(field, part) for part in re.split(r"[()]", truth) if part.strip())
    return {k for k in keys if k}


def values_agree(field: str, predicted: str, truth: str) -> bool:
    key = comparison_key(field, predicted)
    if not key:
        return False
    if field == "manufacturer":
        # Brand names are printed in short or long form ("WEG" vs "WEG Electric"); containment counts.
        truth_key = comparison_key(field, truth)
        return bool(truth_key) and (key in truth_key or truth_key in key)
    return key in _truth_keys(field, truth)


def score_field(field: str, predicted: str | None, truth: str | None) -> Outcome:
    if predicted is None:
        return Outcome.MISSED if truth is not None else Outcome.ABSTAINED_OK
    if truth is None:
        return Outcome.EXTRA
    return Outcome.CORRECT if values_agree(field, predicted, truth) else Outcome.WRONG


def tally(outcomes: list[Outcome]) -> Counter[Outcome]:
    counts: Counter[Outcome] = Counter({outcome: 0 for outcome in Outcome})
    counts.update(outcomes)
    return counts
