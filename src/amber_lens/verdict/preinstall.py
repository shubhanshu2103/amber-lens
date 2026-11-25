"""Pre-install check: does the thing on the nameplate belong in this room?

Deterministic rules only. The reader supplies fields, the records supply expectations, and the verdict comes from the
rules below. A model may later rewrite `explanation`, but it never decides the outcome.

    model_in_schedule       nameplate model is on the equipment schedule (picks the schedule row)
    room_matches_schedule   the scanned room tag is the room the schedule puts that item in
    model_matches_po        a PO line exists for that equipment tag and model
    submittal_approved      the submittal for that model is approved (or approved as noted)

A fuzzy record match never decides a check (passed=None), so a fuzzy-only match is CANT_MATCH and goes to a person.
The nameplate identifier is the READ catalog_number, else the READ model_number. Injection is checked on every field.

Outcome: any check failed -> HOLD. Otherwise any check lacking data -> CANT_MATCH. Otherwise GO.
A known failure outranks missing data, so a wrong room is still reported even if another field was unreadable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Literal, Protocol, TypeVar

from amber_lens.schemas import (
    CheckResult,
    Observation,
    PerceptionResult,
    POLine,
    ReadField,
    ReadStatus,
    ScheduleItem,
    SourceRef,
    Submittal,
    Verdict,
    VerdictCode,
)
from amber_lens.verdict.confidence import compute_confidence, needs_human

MatchType = Literal["exact", "normalised", "alias", "fuzzy", "none"]
T = TypeVar("T")

CHECK_NAMES = ("model_in_schedule", "room_matches_schedule", "model_matches_po", "submittal_approved")
APPROVED = {"approved", "approved_as_noted"}
IDENTIFIER_FIELDS = ("catalog_number", "model_number")


@dataclass(frozen=True)
class Matched(Generic[T]):
    """A record plus how the lookup matched it. Fuzzy is never treated as exact."""

    item: T
    match_type: MatchType


class PreInstallRecords(Protocol):
    """What this check needs from the records layer (#13)."""

    def schedule_rows(self, model_number: str) -> list[Matched[ScheduleItem]]: ...

    def po_lines(self, model_number: str) -> list[Matched[POLine]]: ...

    def submittal_for_model(self, model_number: str) -> Matched[Submittal] | None: ...


def _decided(match_type: str, passed: bool) -> bool | None:
    """A fuzzy match is evidence for a person, not a decision: the check is left open."""
    return None if match_type == "fuzzy" else passed


def _unknown(name: str) -> CheckResult:
    return CheckResult(name=name, passed=None)


def _schedule_src(row: ScheduleItem) -> SourceRef:
    return SourceRef(kind="schedule_row", ref_id=row.equipment_tag, detail=row.drawing_ref)


def _pick_row(rows: list[Matched[ScheduleItem]], room: str | None) -> Matched[ScheduleItem] | None:
    """A single candidate is the row. Several need the room to choose; with no room we cannot resolve it."""
    if len(rows) == 1:
        return rows[0]
    if room is not None:
        return next((r for r in rows if r.item.room_tag == room), None)
    return None


def _run_checks(model: str, room: str | None, field: ReadField, records: PreInstallRecords) -> list[CheckResult]:
    crop = [field.source] if field.source else []
    rows = records.schedule_rows(model)
    if not rows:
        return [CheckResult(name=n, passed=None) for n in CHECK_NAMES]

    row = _pick_row(rows, room)
    if row is None and room is not None:  # several rows, none in the scanned room
        row_for_checks = rows[0]
        rooms = ", ".join(sorted({r.item.room_tag for r in rows}))
        return [
            CheckResult(name="model_in_schedule", passed=_decided(rows[0].match_type, True), match_type=rows[0].match_type,
                        sources=crop + [_schedule_src(row_for_checks.item)]),
            CheckResult(name="room_matches_schedule", passed=False, expected=rooms, found=room, match_type="exact",
                        sources=[SourceRef(kind="room", ref_id=room)] + [_schedule_src(r.item) for r in rows]),
            *[_unknown(n) for n in CHECK_NAMES[2:]],
        ]

    in_schedule = CheckResult(
        name="model_in_schedule", passed=_decided((row or rows[0]).match_type, True),
        match_type=(row or rows[0]).match_type,
        sources=crop + [_schedule_src((row or rows[0]).item)],
    )
    if row is None:  # several rows and no room to choose between them
        return [in_schedule, *[_unknown(n) for n in CHECK_NAMES[1:]]]

    sched = row.item
    if room is None:
        room_check = _unknown("room_matches_schedule")
    else:
        room_check = CheckResult(
            name="room_matches_schedule", passed=room == sched.room_tag, expected=sched.room_tag, found=room,
            match_type="exact", sources=[SourceRef(kind="room", ref_id=room), _schedule_src(sched)],
        )

    lines = records.po_lines(model)
    # a PO line carries the equipment tag when the project has one; otherwise fall back to matching by model
    po = next((m for m in lines if m.item.equipment_tag == sched.equipment_tag), None) or next(
        (m for m in lines if m.item.equipment_tag is None), None
    )
    if po is None:
        po_check = CheckResult(name="model_matches_po", passed=False, expected=f"PO line for {sched.equipment_tag}",
                               found="none", match_type="none")
    else:
        line = po.item
        po_check = CheckResult(
            name="model_matches_po", passed=_decided(po.match_type, True), expected=line.model_number, found=model, match_type=po.match_type,
            sources=[SourceRef(kind="po_line", ref_id=f"{line.po_number}:{line.line}")],
        )

    sub = records.submittal_for_model(model)
    if sub is None:
        sub_check = CheckResult(name="submittal_approved", passed=False, expected="approved", found="no submittal",
                                match_type="none")
    else:
        s = sub.item
        sub_check = CheckResult(
            name="submittal_approved", passed=_decided(sub.match_type, s.status in APPROVED), expected="approved", found=s.status,
            match_type=sub.match_type, sources=[SourceRef(kind="submittal", ref_id=s.submittal_id)],
        )
    return [in_schedule, room_check, po_check, sub_check]


def _explain(code: VerdictCode, checks: list[CheckResult]) -> tuple[str, str]:
    """Plain, deterministic one-liner and next action."""
    failed = [c for c in checks if c.passed is False]
    unknown = [c for c in checks if c.passed is None]
    if code == VerdictCode.HOLD:
        c = failed[0]
        detail = f"expected {c.expected}, found {c.found}" if c.expected else "failed"
        return f"{c.name.replace('_', ' ')}: {detail}.", "Do not install; review the Site PR."
    if code == VerdictCode.CANT_MATCH:
        names = ", ".join(c.name.replace("_", " ") for c in unknown)
        return f"Not enough evidence to decide ({names}).", "Retake the photo or scan the room tag, or send to a person."
    return "Model, room, PO line and submittal all match.", "Clear to install."


def check_pre_install(
    observation: Observation, perception: PerceptionResult, records: PreInstallRecords
) -> Verdict:
    # try the catalog number first, then the model number; use the first one the schedule knows
    ids = [f for n in IDENTIFIER_FIELDS for f in perception.fields if f.name == n and f.status == ReadStatus.READ and f.value]
    field = next((f for f in ids if records.schedule_rows(f.value)), ids[0] if ids else None)
    flags: list[str] = []
    fields = [field] if field else []

    if field is None:
        flags.append("unreadable_field")
        checks = [_unknown(n) for n in CHECK_NAMES]
    else:
        room = observation.room_tag if perception.tag_read_ok else None
        checks = _run_checks(field.value, room, field, records)

    if any(c.passed is False for c in checks):
        code = VerdictCode.HOLD
    elif any(c.passed is None for c in checks):
        code = VerdictCode.CANT_MATCH
    else:
        code = VerdictCode.GO

    # injection is checked on every field, including the free-text lines perception could not parse
    flagged = [f for f in perception.fields if f.injection_flag]
    if flagged:
        flags.append("injection_flag")

    confidence = compute_confidence(checks, fields, tag_read_ok=perception.tag_read_ok)
    explanation, next_action = _explain(code, checks)
    sources = [s for c in checks for s in c.sources]

    return Verdict(
        verdict_id=f"v-{observation.observation_id}-pre_install",
        observation_id=observation.observation_id,
        check_type="pre_install",
        verdict=code,
        checks=checks,
        confidence=confidence,
        needs_human=needs_human(confidence, fields + flagged) or code == VerdictCode.CANT_MATCH,
        explanation=explanation,
        next_action=next_action,
        sources=sources,
        flags=flags,
        latency_ms=perception.latency_ms,
        cost_usd=perception.cost_usd,
    )
