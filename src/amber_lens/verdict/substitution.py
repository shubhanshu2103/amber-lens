"""Substitution check: is what is on the nameplate what the approved submittal says it should be?

Compared field by field against `Submittal.ratings`, keyed by perception's field names (voltage, rated_current, power,
frequency; hp / kw / amps / hz are accepted as aliases).

    model_matches_submittal   the model (or an allowed suffix of it) has a submittal; a fuzzy match decides nothing
    submittal_approved        that submittal is approved or approved as noted; otherwise there is no baseline
    rating_<field>            the nameplate value equals the approved value

Ratings are compared only for an approved, non-fuzzy submittal, and only the ratings it lists: a READ field it does not
list (say frequency) is deliberately left alone, because the approved list defines what is checked.

Outcome: a rating that differs -> DEVIATES. Otherwise anything we could not decide (unread field, ambiguous
multi-rating plate, suffix not on the allowed list, unmapped rating, no approved submittal) -> CANT_MATCH, never assumed
harmless. Otherwise GO. A model whose suffix is not on the allowed list simply has no submittal match, so it is CANT_MATCH.
"""

from __future__ import annotations

import re
from typing import Protocol

from amber_lens.schemas import (
    CheckResult,
    Observation,
    PerceptionResult,
    ReadField,
    ReadStatus,
    SourceRef,
    Submittal,
    Verdict,
    VerdictCode,
)
from amber_lens.verdict.confidence import compute_confidence, needs_human
from amber_lens.verdict.preinstall import APPROVED, IDENTIFIER_FIELDS, Matched, _decided

RATING_FIELDS = {
    "voltage": "voltage", "rated_current": "rated_current", "amps": "rated_current", "current": "rated_current",
    "power": "power", "hp": "power", "kw": "power", "frequency": "frequency", "hz": "frequency",
}


class SubstitutionRecords(Protocol):
    def submittal_for_model(self, model_number: str) -> Matched[Submittal] | None: ...


UNIT_WORDS = {"V": "V", "VAC": "V", "VDC": "V", "A": "A", "AMP": "A", "AMPS": "A", "HP": "HP", "KW": "KW", "W": "W",
              "HZ": "HZ", "KVA": "KVA", "RPM": "RPM"}
KEY_UNITS = {"voltage": "V", "rated_current": "A", "current": "A", "amps": "A", "hp": "HP", "kw": "KW", "hz": "HZ",
             "frequency": "HZ"}
TOKEN = re.compile(r"(?P<num>\d+,\d{1,2}(?!\d)|\d+(?:\.\d+)?)|(?<![A-Za-z])(?P<unit>[A-Za-z]+)(?![A-Za-z])")


def _pairs(text: str) -> list[tuple[str, str | None]]:
    """(number, unit) pairs as printed. A number takes the next known unit after it; wiring letters (delta, Y) are not
    units, and a decimal comma (15,5) is a decimal point while 230,460 is two numbers."""
    tokens = [(m.lastgroup, m.group()) for m in TOKEN.finditer(text)]
    out = []
    for i, (kind, val) in enumerate(tokens):
        if kind != "num":
            continue
        unit = next((UNIT_WORDS[v.upper()] for k, v in tokens[i + 1:] if k == "unit" and v.upper() in UNIT_WORDS), None)
        out.append((format(float(val.replace(",", ".")), "g"), unit))
    return out


def compare_rating(approved: str, found: str, key: str | None = None) -> bool | None:
    """True equal, False different, None cannot tell (the plate shows only part of the approved values, or more).

    The approved value may list several values (208-230/460 V): all of them are compared as a set, so the same text on
    the plate matches, a different second value (230/575 V) is a mismatch, and a plate showing only 460 V is undecided.

    A unit missing from the approved value is taken from its key (hp -> HP). Values in another unit are different values,
    so 50 HP against 50 kW is a mismatch, while a second unit in brackets (1.0 HP (0.75 kW)) is ignored.
    """
    ap, fp = _pairs(approved), _pairs(found)
    if not ap or not fp:
        return None if (ap or fp) else approved.strip().upper() == found.strip().upper()
    unit = next((u for _, u in ap if u), None) or KEY_UNITS.get((key or "").lower())
    wanted = {n for n, u in ap if u in (None, unit)}  # every value approved, e.g. {208, 230, 460} for 208-230/460 V
    seen = {n for n, u in fp if unit is None or u in (None, unit)}
    if not seen:
        return False  # the plate states this rating only in another unit
    if wanted == seen:
        return True
    if wanted < seen or seen < wanted:
        return None  # the plate shows only part of what was approved, or more than was
    return False


def _unknown(name: str) -> CheckResult:
    return CheckResult(name=name, passed=None)


def _combine(results: list[bool | None]) -> bool | None:
    """Several approved keys for one plate field (hp and kw): pass only if all pass, deviate only if all differ."""
    if all(r is True for r in results):
        return True
    if all(r is False for r in results):
        return False
    return None


def _rating_checks(sub: Submittal, fields: list[ReadField], sub_src: SourceRef) -> list[CheckResult]:
    """Only ratings the approved submittal lists are compared; a READ field it does not list is left alone."""
    groups: dict[str, list[tuple[str, str]]] = {}
    for key, approved in sub.ratings.items():
        groups.setdefault(RATING_FIELDS.get(key.lower()) or f"?{key.lower()}", []).append((key, approved))
    out = []
    for target, items in groups.items():
        expected = ", ".join(f"{k}={v}" if len(items) > 1 else v for k, v in items)
        field = next((f for f in fields if f.name == target and f.status == ReadStatus.READ and f.value), None)
        if target.startswith("?") or field is None:
            out.append(CheckResult(name=f"rating_{target.lstrip('?')}", passed=None, expected=expected))
            continue
        passed = _combine([compare_rating(v, field.value, k) for k, v in items])
        out.append(CheckResult(name=f"rating_{target}", passed=passed, expected=expected, found=field.value,
                               match_type="exact", sources=[field.source, sub_src]))
    return out


def _explain(code: VerdictCode, checks: list[CheckResult]) -> tuple[str, str]:
    if code == VerdictCode.DEVIATES:
        bad = [c for c in checks if c.passed is False]
        parts = "; ".join(f"{c.name.removeprefix('rating_')}: approved {c.expected}, nameplate {c.found}" for c in bad)
        return f"Nameplate differs from the approved submittal ({parts}).", "Do not install; review the Site PR."
    if code == VerdictCode.CANT_MATCH:
        names = ", ".join(c.name.replace("_", " ") for c in checks if c.passed is None)
        return f"Not enough evidence to compare with the submittal ({names}).", "Retake the photo or send to a person."
    return "Model and every rating match the approved submittal.", "Clear to install."


def check_substitution(observation: Observation, perception: PerceptionResult, records: SubstitutionRecords) -> Verdict:
    ids = [f for n in IDENTIFIER_FIELDS for f in perception.fields if f.name == n and f.status == ReadStatus.READ and f.value]
    field = next((f for f in ids if records.submittal_for_model(f.value)), ids[0] if ids else None)
    flags: list[str] = []
    used: list[ReadField] = [field] if field else []

    sub = records.submittal_for_model(field.value) if field else None
    if field is None:
        flags.append("unreadable_field")
    if sub is None:
        checks = [_unknown("model_matches_submittal")]
    else:
        s = sub.item
        sub_src = SourceRef(kind="submittal", ref_id=s.submittal_id)
        checks = [
            CheckResult(name="model_matches_submittal", passed=_decided(sub.match_type, True), expected=s.model_number,
                        found=field.value, match_type=sub.match_type, sources=[field.source, sub_src]),
            CheckResult(name="submittal_approved", passed=True if s.status in APPROVED else None, expected="approved",
                        found=s.status, match_type="exact", sources=[sub_src]),
        ]
        if s.status in APPROVED and sub.match_type != "fuzzy":
            checks += _rating_checks(s, perception.fields, sub_src) or [_unknown("ratings_present")]
        used += [f for f in perception.fields if f.name in set(RATING_FIELDS.values()) and f.status == ReadStatus.READ]

    if any(c.passed is False for c in checks):
        code = VerdictCode.DEVIATES
    elif any(c.passed is None for c in checks):
        code = VerdictCode.CANT_MATCH
    else:
        code = VerdictCode.GO

    flagged = [f for f in perception.fields if f.injection_flag]
    if flagged:
        flags.append("injection_flag")
    confidence = compute_confidence(checks, used, injection=bool(flagged))
    explanation, next_action = _explain(code, checks)

    return Verdict(
        verdict_id=f"v-{observation.observation_id}-substitution",
        observation_id=observation.observation_id,
        check_type="substitution",
        verdict=code,
        checks=checks,
        confidence=confidence,
        needs_human=needs_human(confidence, used + flagged) or code == VerdictCode.CANT_MATCH,
        explanation=explanation,
        next_action=next_action,
        sources=[src for c in checks for src in c.sources],
        flags=flags,
        latency_ms=perception.latency_ms,
        cost_usd=perception.cost_usd,
    )
