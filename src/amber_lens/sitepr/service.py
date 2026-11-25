"""Site PR lifecycle on top of the ledger: draft -> self-check -> review -> write once -> verify."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from amber_lens.schemas import LedgerEvent, SitePR, SitePRStatus

from .ledger import Ledger
from .record_store import MockRecordStore
from .state import TransitionError, evidence_pack_hash, rebuild

SYSTEM = "sitepr"
# Only a project manager approves. Site engineers, storekeepers and inspectors capture findings, so letting them
# approve their own would skip the second person. Widen deliberately if that ever changes.
REVIEWER_ROLES = ("project manager",)


class SitePRService:
    def __init__(self, ledger: Ledger, store: MockRecordStore, fault: Callable[[str], None] | None = None):
        self.ledger = ledger
        self.store = store
        self._fault = fault or (lambda point: None)  # test hook: lets a test kill the process at a named point

    # -- helpers ----------------------------------------------------------- #
    def _emit(self, site_pr_id: str, type_: str, actor: str, payload: dict | None = None, key: str | None = None):
        self.ledger.append(
            LedgerEvent(
                event_id=uuid.uuid4().hex,
                site_pr_id=site_pr_id,
                type=type_,
                actor=actor,
                payload=payload or {},
                idempotency_key=key,
            )
        )

    def get(self, site_pr_id: str) -> SitePR:
        return rebuild(self.ledger.events(site_pr_id))

    def list(self, status: SitePRStatus | None = None) -> list[SitePR]:
        prs = [self.get(i) for i in self.ledger.site_pr_ids()]
        return [p for p in prs if status is None or p.status == status]

    # -- lifecycle --------------------------------------------------------- #
    def draft(self, pr: SitePR) -> SitePR:
        pr = pr.model_copy(update={"status": SitePRStatus.DRAFT, "evidence_hash": None})
        self._emit(pr.site_pr_id, "drafted", SYSTEM, {"site_pr": pr.model_dump(mode="json")})
        return self.get(pr.site_pr_id)

    def self_check(self, site_pr_id: str, note: str, withdraw: bool = False, detail: dict | None = None) -> SitePR:
        """Record the self-check result; withdraw the PR if the fix would be wrong. `detail` (e.g. the sighting) is logged."""
        self._emit(site_pr_id, "self_checked", SYSTEM, {"note": note, **(detail or {})})
        if withdraw:
            self._emit(site_pr_id, "withdrawn", SYSTEM, {"reason": note, **(detail or {})})
        return self.get(site_pr_id)

    def submit(self, site_pr_id: str) -> SitePR:
        self._emit(site_pr_id, "submitted", SYSTEM)
        return self.get(site_pr_id)

    def approve(self, site_pr_id: str, reviewer_role: str, note: str = "") -> SitePR:
        """Freeze the evidence pack hash at approval. Only a person's role may approve, never the system."""
        if reviewer_role not in REVIEWER_ROLES:
            raise TransitionError(f"{site_pr_id}: {reviewer_role!r} is not a reviewer role; only a person may approve")
        pr = self.get(site_pr_id)
        self._emit(
            site_pr_id,
            "approved",
            reviewer_role,
            {"evidence_hash": evidence_pack_hash(pr), "note": note},
        )
        return self.get(site_pr_id)

    def reject(self, site_pr_id: str, reviewer_role: str, note: str = "") -> SitePR:
        self._emit(site_pr_id, "rejected", reviewer_role, {"note": note})
        return self.get(site_pr_id)

    def write(self, site_pr_id: str) -> SitePR:
        """Apply an approved Site PR to the record store exactly once. Safe to call again after a crash."""
        pr = self.get(site_pr_id)
        if pr.status != SitePRStatus.APPROVED or not pr.evidence_hash:
            raise TransitionError(f"{site_pr_id}: no write without an approved event (status {pr.status.value})")
        if evidence_pack_hash(pr) != pr.evidence_hash:
            raise TransitionError(f"{site_pr_id}: evidence changed after approval")
        applied = self.store.apply(pr.idempotency_key, pr.changes)
        self._fault("after_apply")  # crash window: store written, ledger not yet
        self._emit(site_pr_id, "written", SYSTEM, {"applied_now": applied}, key=pr.idempotency_key)
        return self.get(site_pr_id)

    def verify(self, site_pr_id: str) -> SitePR:
        """Read back through the store's separate read path. A mismatch reopens the Site PR."""
        pr = self.get(site_pr_id)
        if pr.status != SitePRStatus.WRITTEN:
            raise TransitionError(f"{site_pr_id}: can only verify a written Site PR (status {pr.status.value})")
        bad = [
            f"{c.record_kind}:{c.record_id}.{c.field} expected {c.new_value!r}, found "
            f"{self.store.read(c.record_kind, c.record_id, c.field)!r}"
            for c in pr.changes
            if self.store.read(c.record_kind, c.record_id, c.field) != c.new_value
        ]
        if bad:
            self._emit(site_pr_id, "reopened", SYSTEM, {"reason": "read-back mismatch", "mismatches": bad})
        else:
            self._emit(site_pr_id, "verified", SYSTEM)
        return self.get(site_pr_id)

    def reopen(self, site_pr_id: str, reason: str, recurrence: bool = False, refresh: SitePR | None = None) -> SitePR:
        """Reopen. `refresh` is the new finding of a recurrence: its evidence replaces the old before re-review."""
        payload = {"reason": reason, "recurrence": recurrence}
        if refresh is not None:
            payload["refresh"] = refresh.model_dump(mode="json")
        self._emit(site_pr_id, "reopened", SYSTEM, payload)
        return self.get(site_pr_id)

    def recover(self) -> list[str]:
        """After a restart: write approved-but-unwritten Site PRs, then verify every written one.

        Returns the ids it wrote. A PR that died after `written` is verified here too, so it never sits unverified.
        """
        done = []
        for pr in self.list(SitePRStatus.APPROVED):
            self.write(pr.site_pr_id)
            done.append(pr.site_pr_id)
        for pr in self.list(SitePRStatus.WRITTEN):
            self.verify(pr.site_pr_id)
        return done
