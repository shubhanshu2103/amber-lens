"""Self-check on a drafted claim, before a person sees it (#24).

Two ways a claim can be wrong without the check that made it being at fault:
  - "the item is missing", but it was seen somewhere in the last 7 days (the sightings table, #14);
  - "re-order it", but an identical claim (same field, same value) is already open.
Either one withdraws the draft and logs why, citing the sighting or the other Site PR. An open Site PR that sets the same
field to a different value is a conflict, not a duplicate: the draft stays and the note names the other one. Anything
else is recorded as a clean self-check and the draft goes on to review. A reopened Site PR can be self-checked too.

A sighting only counts for the same item: with an equipment tag on the claim, the sighting needs that same tag. Without
one the match is by model only, which is weaker (another unit of that model could have been the one seen), and the note
says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from amber_lens.schemas import Sighting, SitePR, SitePRStatus, utcnow

from .service import SitePRService
from .state import issue_key

DEFAULT_WINDOW_DAYS = 7
OPEN = {SitePRStatus.PENDING_REVIEW, SitePRStatus.APPROVED, SitePRStatus.WRITTEN, SitePRStatus.REOPENED}


@dataclass(frozen=True)
class ItemRef:
    model_number: str
    equipment_tag: str | None = None


class SightingsLookup(Protocol):
    def sightings_for_model(self, model_number: str) -> list[Sighting]: ...


def _latest_sighting(item: ItemRef, sightings: SightingsLookup, now: datetime, window: timedelta) -> Sighting | None:
    hits = [
        s for s in sightings.sightings_for_model(item.model_number)
        if now - window <= s.seen_at <= now and (item.equipment_tag is None or s.equipment_tag == item.equipment_tag)
    ]
    return max(hits, key=lambda s: s.seen_at, default=None)


def _changes(pr: SitePR) -> frozenset[tuple[str, str, str, str]]:
    return frozenset((c.record_kind, c.record_id, c.field, c.new_value) for c in pr.changes)


def open_prs_for_issue(service: SitePRService, pr: SitePR) -> list[SitePR]:
    """Other Site PRs on the same record fields that are still open, in the order they were drafted.

    A draft only counts if it was drafted before `pr` (so two drafts of one claim do not withdraw each other); a `pr` that
    is not in the ledger yet comes after every draft in it.
    """
    order = {i: n for n, i in enumerate(service.ledger.site_pr_ids())}
    mine = order.get(pr.site_pr_id, len(order))
    return [
        other for other in service.list()
        if other.site_pr_id != pr.site_pr_id and issue_key(other) == issue_key(pr)
        and (other.status in OPEN or (other.status == SitePRStatus.DRAFT and order[other.site_pr_id] < mine))
    ]


def self_check_claim(
    service: SitePRService,
    site_pr_id: str,
    item: ItemRef,
    sightings: SightingsLookup,
    now: datetime | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> SitePR:
    now = now or utcnow()
    if now.tzinfo is None:
        raise ValueError("now must have a timezone (use datetime.now(UTC)); sightings are timezone-aware")
    pr = service.get(site_pr_id)

    seen = _latest_sighting(item, sightings, now, timedelta(days=window_days))
    if seen is not None:
        how = f"tag {item.equipment_tag}" if item.equipment_tag else "model only"
        note = (f"Seen in {seen.room_tag} on {seen.seen_at.date().isoformat()} (observation {seen.observation_id}, "
                f"matched by {how}), so the claim is withdrawn.")
        return service.self_check(site_pr_id, note, withdraw=True, detail={"sighting": seen.model_dump(mode="json")})

    others = open_prs_for_issue(service, pr)
    dup = next((o for o in others if _changes(o) == _changes(pr)), None)
    if dup is not None:
        note = f"{dup.site_pr_id} already proposes the same change ({dup.status.value}), so this draft is withdrawn."
        return service.self_check(site_pr_id, note, withdraw=True, detail={"duplicate_of": dup.site_pr_id})
    if others:
        # same record field, different value: both go to the reviewer, who needs to see the disagreement
        clash = others[0]
        value = clash.changes[0].new_value
        note = (f"Checked: no sighting of {item.model_number} in the last {window_days} days, but this conflicts with "
                f"{clash.site_pr_id} ({clash.status.value}), which sets the same field to {value}.")
        return service.self_check(site_pr_id, note, detail={"conflicts_with": clash.site_pr_id})

    note = f"Checked: no sighting of {item.model_number} in the last {window_days} days and no open Site PR for the same change."
    return service.self_check(site_pr_id, note)
