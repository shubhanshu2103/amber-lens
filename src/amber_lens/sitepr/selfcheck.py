"""Self-check on a drafted claim, before a person sees it (#24).

Two ways a claim can be wrong without the check that made it being at fault:
  - "the item is missing", but it was seen somewhere in the last 7 days (the sightings table, #14);
  - "re-order it", but an identical claim is already open.
Either one withdraws the draft and logs why, citing the sighting or the other Site PR. Anything else is recorded as a
clean self-check and the draft goes on to review.

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


def _open_duplicate(service: SitePRService, pr: SitePR) -> SitePR | None:
    for other in service.list():
        if other.site_pr_id == pr.site_pr_id or issue_key(other) != issue_key(pr):
            continue
        # a draft only blocks a later one, so two drafts of the same claim do not withdraw each other
        if other.status in OPEN or (other.status == SitePRStatus.DRAFT and other.site_pr_id < pr.site_pr_id):
            return other
    return None


def self_check_claim(
    service: SitePRService,
    site_pr_id: str,
    item: ItemRef,
    sightings: SightingsLookup,
    now: datetime | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> SitePR:
    now = now or utcnow()
    pr = service.get(site_pr_id)

    seen = _latest_sighting(item, sightings, now, timedelta(days=window_days))
    if seen is not None:
        how = f"tag {item.equipment_tag}" if item.equipment_tag else "model only"
        note = (f"Seen in {seen.room_tag} on {seen.seen_at.date().isoformat()} (observation {seen.observation_id}, "
                f"matched by {how}), so the claim is withdrawn.")
        return service.self_check(site_pr_id, note, withdraw=True, detail={"sighting": seen.model_dump(mode="json")})

    dup = _open_duplicate(service, pr)
    if dup is not None:
        note = f"{dup.site_pr_id} already proposes the same change ({dup.status.value}), so this draft is withdrawn."
        return service.self_check(site_pr_id, note, withdraw=True, detail={"duplicate_of": dup.site_pr_id})

    note = f"Checked: no sighting of {item.model_number} in the last {window_days} days and no open Site PR for the same change."
    return service.self_check(site_pr_id, note)
