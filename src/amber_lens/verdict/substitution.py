"""Substitution check: is what is on the nameplate what the approved submittal says it should be?

Compared field by field against `Submittal.ratings`, keyed by perception's field names (voltage, rated_current, power,
frequency; hp / kw / amps / hz are accepted as aliases).

    model_matches_submittal   the model (or an allowed suffix of it) has a submittal; a fuzzy match decides nothing
    submittal_approved        that submittal is approved or approved as noted; otherwise there is no baseline
    rating_<field>            the nameplate value equals the approved value

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


def _numbers(s: str) -> list[str]:
    return [str(float(n)).rstrip("0").rstrip(".") for n in re.findall(r"\d+(?:\.\d+)?", s)]


def _unit(s: str) -> str:
    return re.sub(r"[^A-Z]", "", s.upper())


def compare_rating(approved: str, found: str) -> bool | None:
    """True equal, False different, None cannot tell (a multi-rating plate that contains the approved value)."""
    an, fn = _numbers(approved), _numbers(found)
    if not an or not fn:
        return None if (an or fn) else approved.strip().upper() == found.strip().upper()
    au, fu = _unit(approved), _unit(found)
    if au and fu and au != fu:
        return False
    if an == fn:
        return True
    if set(an) < set(fn) or set(fn) < set(an):
        return None
    return False


def _unknown(name: str) -> CheckResult:
    return CheckResult(name=name, passed=None)


def _rating_checks(sub: Submittal, fields: list[ReadField], model_src: list[SourceRef]) -> list[CheckResult]:
    out = []
    for key, approved in sub.ratings.items():
        target = RATING_FIELDS.get(key.lower())
        name = f"rating_{target or key.lower()}"
        field = next((f for f in fields if f.name == target and f.status == ReadStatus.READ and f.value), None)
        if target is None or field is None:
            out.append(CheckResult(name=name, passed=None, expected=approved))
            continue
        out.append(CheckResult(
            name=name, passed=compare_rating(approved, field.value), expected=approved, found=field.value,
            match_type="exact", sources=[field.source, *model_src],
        ))
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
            *(_rating_checks(s, perception.fields, [sub_src]) or [_unknown("ratings_present")]),
        ]
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
    confidence = compute_confidence(checks, used)
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
