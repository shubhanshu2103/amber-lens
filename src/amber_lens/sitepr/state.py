"""Pure Site PR state logic: which ledger event moves which status, and rebuilding a Site PR from events."""

from __future__ import annotations

import hashlib
import json
import re

from amber_lens.schemas import (
    SITEPR_TRANSITIONS,
    LedgerEvent,
    SitePR,
    SitePRStatus,
)

S = SitePRStatus

# Event type -> status it moves the Site PR to. `self_checked` records a note and keeps the status.
EVENT_STATUS: dict[str, SitePRStatus | None] = {
    "drafted": S.DRAFT,
    "self_checked": None,
    "withdrawn": S.WITHDRAWN,
    "submitted": S.PENDING_REVIEW,
    "approved": S.APPROVED,
    "rejected": S.REJECTED,
    "written": S.WRITTEN,
    "verified": S.VERIFIED,
    "reopened": S.REOPENED,
}


class TransitionError(ValueError):
    """The event is not allowed from the current status."""


def next_status(current: SitePRStatus | None, event_type: str) -> SitePRStatus:
    """Status after `event_type`, or raise TransitionError. `current` is None before the first event."""
    if event_type not in EVENT_STATUS:
        raise TransitionError(f"unknown event type {event_type!r}")
    if current is None:
        if event_type != "drafted":
            raise TransitionError("a Site PR must start with a 'drafted' event")
        return S.DRAFT
    if event_type == "drafted":
        raise TransitionError("Site PR already drafted")
    target = EVENT_STATUS[event_type]
    if target is None:  # self_checked: while drafting, or after a reopen (the new evidence needs its own check)
        if current not in (S.DRAFT, S.REOPENED):
            raise TransitionError(f"self_checked not allowed from {current.value}")
        return current
    if target not in SITEPR_TRANSITIONS[current]:
        raise TransitionError(f"{current.value} -> {target.value} is not allowed (event {event_type})")
    return target


def evidence_pack_hash(pr: SitePR) -> str:
    """sha256 of the evidence a reviewer approves: finding, proposed changes, evidence sources."""
    pack = {
        "finding": pr.finding,
        "changes": [c.model_dump(mode="json") for c in pr.changes],
        "evidence": [e.model_dump(mode="json") for e in pr.evidence],
    }
    return hashlib.sha256(json.dumps(pack, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def issue_key(pr: SitePR) -> frozenset[tuple[str, str, str]]:
    """Which record fields a Site PR proposes to change. Two Site PRs with the same key are about the same issue."""
    return frozenset((c.record_kind, c.record_id, c.field) for c in pr.changes)


def key_for_version(base_key: str, version: int) -> str:
    """'sitepr-0042:claim:v1' with version 2 -> 'sitepr-0042:claim:v2'."""
    if re.search(r":v\d+$", base_key):
        return re.sub(r":v\d+$", f":v{version}", base_key)
    return f"{base_key}:v{version}"


def rebuild(events: list[LedgerEvent]) -> SitePR:
    """Replay events (oldest first) into the current Site PR. Raises TransitionError on an illegal history."""
    if not events:
        raise TransitionError("no events")
    status: SitePRStatus | None = None
    pr: SitePR | None = None
    for ev in events:
        status = next_status(status, ev.type)
        if ev.type == "drafted":
            pr = SitePR.model_validate(ev.payload["site_pr"])
        assert pr is not None
        if ev.type == "self_checked":
            pr = pr.model_copy(update={"self_check_note": ev.payload.get("note")})
        elif ev.type == "approved":
            pr = pr.model_copy(update={"evidence_hash": ev.payload["evidence_hash"]})
        elif ev.type == "reopened":
            version = pr.idempotency_version + 1
            fresh = ev.payload.get("refresh")  # a recurrence brings new evidence; the reviewer must not see the old
            carried = {}
            if fresh:
                new = SitePR.model_validate(fresh)
                carried = {"verdict_id": new.verdict_id, "finding": new.finding, "changes": new.changes,
                           "evidence": new.evidence, "confidence": new.confidence, "impact": new.impact}
            pr = pr.model_copy(
                update={
                    **carried,
                    "self_check_note": None,
                    "idempotency_version": version,
                    "idempotency_key": key_for_version(pr.idempotency_key, version),
                    "recurrence_count": pr.recurrence_count + (1 if ev.payload.get("recurrence") else 0),
                    "evidence_hash": None,
                }
            )
        pr = pr.model_copy(update={"status": status})
    assert pr is not None
    return pr
