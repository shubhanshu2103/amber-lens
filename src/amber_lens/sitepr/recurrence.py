"""Reopen on recurrence (#25).

An approved fix is not trusted forever. When a new finding proposes the same change to the same record field as a
*verified* Site PR, the old Site PR is reopened with its recurrence count raised, instead of a second Site PR being
drafted. The reopened Site PR carries the new finding and evidence, gets a new idempotency key so the fix can be written
again, and goes back through review. If a Site PR on the same field is already open, that one is returned instead. The
caller can run `self_check_claim` on the returned Site PR (a reopened one allows it). Anything else is drafted as new.
"""

from __future__ import annotations

from amber_lens.schemas import SitePR, SitePRStatus

from .selfcheck import open_prs_for_issue
from .service import SitePRService
from .state import issue_key


def report_finding(service: SitePRService, new_pr: SitePR) -> SitePR:
    open_now = open_prs_for_issue(service, new_pr)
    if open_now:  # a Site PR on this field is already in flight: do not open a second one beside it
        return open_now[0]
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
