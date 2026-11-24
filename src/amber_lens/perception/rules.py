"""Format rules: does a read value look like a plausible value for its field?

A rule never fixes a value. It only says pass or fail; a failing value is not READ.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable

# Nominal voltages printed on equipment: IEC 60038 low-voltage series, ANSI C84.1 / NEMA MG 1 motor
# nameplate voltages, and the extra-low control voltages. 440 is kept because legacy and marine
# plates print it.
STANDARD_VOLTAGES: frozenset[int] = frozenset(
    {12, 24, 48, 100, 110, 115, 120, 127, 190, 200, 208, 220, 230, 240, 277, 347, 380, 400, 415, 440, 460, 480,
     575, 600, 690, 1000}
)
STANDARD_FREQUENCIES: frozenset[int] = frozenset({50, 60, 400})
MAX_CURRENT_A = 5000.0

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
# A number that is a tolerance, like the 10 in "415 +/- 10 %".
_TOLERANCE = re.compile(r"(?:±|\+/-|\+-)\s*\d+(?:[.,]\d+)?\s*%|\d+(?:[.,]\d+)?\s*%")
_MODEL_CHARS = re.compile(r"[A-Za-z0-9][A-Za-z0-9 \-./]*")


def _clean(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _numbers(value: str) -> list[float]:
    """Numbers in a value, ignoring tolerances; a decimal comma counts as a decimal point."""
    stripped = _TOLERANCE.sub(" ", value)
    return [float(n.replace(",", ".")) for n in _NUMBER.findall(stripped)]


# Rule R3: the only words a rating may contain are its own unit words, connection marks and
# input / output annotations; any other letter (a stray "Y" glued to "1.82") fails the rule.
_RATING_WORDS: dict[str, re.Pattern[str]] = {
    "voltage": re.compile(r"(?:v|volts?|vac|vdc|ac|dc|δ|d|y|delta|star)+|input|output|primary|secondary"),
    "rated_current": re.compile(r"a|amps?|fla|rla|input|output"),
    "power": re.compile(r"hp|kw|kva|w|va|input|output"),
    "frequency": re.compile(r"hz|hertz|cycles?"),
}
_LETTER_RUN = re.compile(r"[^\W\d_]+")


def _only_own_words(field: str, text: str) -> bool:
    return all(_RATING_WORDS[field].fullmatch(word) for word in _LETTER_RUN.findall(text.casefold()))


def model_number_ok(value: str) -> bool:
    text = _clean(value)
    if not 3 <= len(text) <= 32 or not _MODEL_CHARS.fullmatch(text):
        return False
    if not any(c.isdigit() for c in text) or text.count(" ") > 3:
        return False
    # A rating that landed in the model field, e.g. "460 V" or "1760 RPM".
    return re.fullmatch(r"[\d.,/\- ]+(?:v|a|hz|hp|kw|kva|rpm)", text.casefold()) is None


def voltage_ok(value: str) -> bool:
    text = _clean(value)
    if len(text) > 48 or not _only_own_words("voltage", text):
        return False
    numbers = _numbers(text)
    return bool(numbers) and all(n.is_integer() and int(n) in STANDARD_VOLTAGES for n in numbers)


def rated_current_ok(value: str) -> bool:
    text = _clean(value)
    if len(text) > 48 or not _only_own_words("rated_current", text):
        return False
    numbers = _numbers(text)
    return bool(numbers) and all(0 < n <= MAX_CURRENT_A for n in numbers)


def power_ok(value: str) -> bool:
    text = _clean(value).casefold()
    if len(text) > 48 or not _only_own_words("power", text):
        return False
    return re.search(r"(?:\d+(?:[.,]\d+)?|\d+/\d+)\s*(?:hp|kw|kva|w|va)(?![a-z])", text) is not None


def frequency_ok(value: str) -> bool:
    text = _clean(value)
    if len(text) > 32 or not _only_own_words("frequency", text):
        return False
    numbers = _numbers(text)
    if not numbers or not all(0 < n <= 400 for n in numbers):
        return False
    return any(n.is_integer() and int(n) in STANDARD_FREQUENCIES for n in numbers)


def manufacturer_ok(value: str) -> bool:
    text = _clean(value)
    letters = sum(c.isalpha() for c in text)
    digits = sum(c.isdigit() for c in text)
    # At least 3 letters, so ABB and WEG pass but a two-letter logo like "ee" does not.
    return 3 <= len(text) <= 60 and letters >= 3 and letters >= digits


FORMAT_RULES: dict[str, Callable[[str], bool]] = {
    "model_number": model_number_ok,
    "catalog_number": model_number_ok,
    "voltage": voltage_ok,
    "rated_current": rated_current_ok,
    "power": power_ok,
    "frequency": frequency_ok,
    "manufacturer": manufacturer_ok,
}


# Printed labels accepted per field, compared without case, spaces, dots, colons or '#'.
# Anything else the model reports as a label is dropped, so free text never reaches a source detail.
PRINTED_LABELS: dict[str, frozenset[str]] = {
    "model_number": frozenset({"MODEL", "MODELNO", "MODELNUMBER", "MOD", "MODNO", "TYPE", "TYP", "TYPENO"}),
    "catalog_number": frozenset(
        {"CAT", "CATNO", "CATNUMBER", "CATALOG", "CATALOGNO", "CATALOGNUMBER", "CATALOGUENO", "ORDNO", "ORDNR",
         "ORDERNO", "ORDERNUMBER"}
    ),
    "voltage": frozenset({"V", "VOLT", "VOLTS", "VOLTAGE", "RATEDVOLTAGE", "INPUT", "OUTPUT", "PRIMARY",
                          "SECONDARY"}),
    "rated_current": frozenset({"A", "AMP", "AMPS", "AMPERES", "FLA", "FLAMPS", "RLA", "CURRENT", "RATEDCURRENT",
                                "INPUT", "OUTPUT"}),
    "power": frozenset({"HP", "KW", "KVA", "POWER", "OUTPUT", "RATEDOUTPUT"}),
    "frequency": frozenset({"HZ", "HERTZ", "FREQ", "FREQUENCY", "CYCLES"}),
    "manufacturer": frozenset(),
}


def label_key(label: str) -> str:
    return re.sub(r"[\s.:#]", "", unicodedata.normalize("NFKC", label)).upper()


def allowed_label(field: str, label: str | None) -> str | None:
    """The printed label, whitespace collapsed, if it is a known label for the field; otherwise None."""
    if label is None or len(label) > 24:
        return None
    return _clean(label) if label_key(label) in PRINTED_LABELS[field] else None


def check_format(field: str, value: str | None) -> bool | None:
    """True / False for a value, None when there is no value to check. Unknown fields raise KeyError."""
    rule = FORMAT_RULES[field]
    return None if value is None else rule(value)


POWER_UNIT_LABELS: frozenset[str] = frozenset({"HP", "KW", "KVA"})
_BARE_NUMBER = re.compile(r"\d+(?:[.,]\d+)?|\d+/\d+|\d+ \d+/\d+")


def attach_power_unit(value: str, printed_label: str | None) -> str | None:
    """A bare power number gets its printed unit label (HP, kW, kVA): '3' + 'HP' -> '3 HP'; else None."""
    if printed_label is None or not _BARE_NUMBER.fullmatch(_clean(value)):
        return None
    label = allowed_label("power", printed_label)
    if label is None or label_key(label) not in POWER_UNIT_LABELS:
        return None
    return f"{_clean(value)} {label}"
