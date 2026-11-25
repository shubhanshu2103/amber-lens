"""Reopen on recurrence (#25).

An approved fix is not trusted forever. When a new finding proposes the same change to the same record field as a
*verified* Site PR, the old Site PR is reopened with its recurrence count raised, instead of a second Site PR being
drafted. The reopened Site PR carries the new finding and evidence, gets a new idempotency key so the fix can be written
again, and goes back through review. Anything else is drafted as a new Site PR.
"""

from __future__ import annotations

from amber_lens.schemas import SitePR, SitePRStatus

from .service import SitePRService
from .state import issue_key


def report_finding(service: SitePRService, new_pr: SitePR) -> SitePR:
    key = issue_key(new_pr)
    earlier = [p for p in service.list(SitePRStatus.VERIFIED) if issue_key(p) == key]
    if not earlier:
        return service.draft(new_pr)
    return service.reopen(
        earlier[-1].site_pr_id,
        f"recurred: {new_pr.finding} (new evidence from {new_pr.verdict_id})",
        recurrence=True,
        refresh=new_pr,
    )
