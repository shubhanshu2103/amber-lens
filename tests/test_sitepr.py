import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from amber_lens.schemas import BBox, RecordChange, SitePR, SitePRStatus, SourceRef
from amber_lens.sitepr import Ledger, MockRecordStore, SitePRService, TransitionError, rebuild

EVID = [SourceRef(kind="photo_crop", ref_id="obs-1", bbox=BBox(x=1, y=1, w=5, h=5))]


def make_pr(pid="sitepr-0042"):
    return SitePR(
        site_pr_id=pid,
        verdict_id="v-1",
        finding="Delivered qty 10 vs PO 12",
        changes=[
            RecordChange(record_kind="delivery", record_id="D-7", field="qty_received", old_value="12", new_value="10")
        ],
        evidence=EVID,
        confidence=0.9,
        idempotency_key=f"{pid}:claim:v1",
    )


@pytest.fixture
def svc(tmp_path):
    store = MockRecordStore(tmp_path / "store.db")
    store.seed("delivery", "D-7", "qty_received", "12")
    return SitePRService(Ledger(tmp_path / "ledger.db"), store)


def approved(svc, pid="sitepr-0042"):
    svc.draft(make_pr(pid))
    svc.self_check(pid, "no recent sighting")
    svc.submit(pid)
    return svc.approve(pid, "project manager")


def test_happy_path_writes_once_and_verifies(svc):
    approved(svc)
    pr = svc.write("sitepr-0042")
    assert pr.status == SitePRStatus.WRITTEN
    assert svc.verify("sitepr-0042").status == SitePRStatus.VERIFIED
    assert svc.store.read("delivery", "D-7", "qty_received") == "10"
    assert svc.store.write_count("sitepr-0042:claim:v1") == 1


def test_no_write_without_approval(svc):
    svc.draft(make_pr())
    svc.submit("sitepr-0042")
    with pytest.raises(TransitionError):
        svc.write("sitepr-0042")
    assert svc.store.read("delivery", "D-7", "qty_received") == "12"


def test_illegal_transitions_rejected(svc):
    svc.draft(make_pr())
    with pytest.raises(TransitionError):
        svc.approve("sitepr-0042", "project manager")  # draft -> approved
    svc.submit("sitepr-0042")
    svc.reject("sitepr-0042", "site engineer", "wrong")
    with pytest.raises(TransitionError):
        svc.submit("sitepr-0042")  # rejected is terminal


def test_self_check_can_withdraw(svc):
    svc.draft(make_pr())
    pr = svc.self_check("sitepr-0042", "item seen in L4 yesterday", withdraw=True)
    assert pr.status == SitePRStatus.WITHDRAWN
    assert pr.self_check_note == "item seen in L4 yesterday"


def test_ledger_is_append_only(svc, tmp_path):
    svc.draft(make_pr())
    con = sqlite3.connect(tmp_path / "ledger.db")
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("UPDATE events SET actor='x'")
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("DELETE FROM events")


def test_evidence_hash_frozen_at_approval(svc):
    pr = approved(svc)
    assert len(pr.evidence_hash) == 64
    assert rebuild(svc.ledger.events("sitepr-0042")).evidence_hash == pr.evidence_hash


def test_write_is_idempotent_on_key(svc):
    approved(svc)
    pr = svc.get("sitepr-0042")
    assert svc.store.apply(pr.idempotency_key, pr.changes) is True
    assert svc.store.apply(pr.idempotency_key, pr.changes) is False
    assert svc.store.write_count(pr.idempotency_key) == 1


def test_readback_mismatch_reopens_and_bumps_key(svc):
    approved(svc)
    svc.write("sitepr-0042")
    svc.store.seed("delivery", "D-7", "qty_received", "99")  # something else overwrote it
    pr = svc.verify("sitepr-0042")
    assert pr.status == SitePRStatus.REOPENED
    assert pr.idempotency_version == 2 and pr.idempotency_key.endswith(":v2")
    assert pr.recurrence_count == 0
    # re-review and re-write lands, because the key moved to v2
    svc.submit("sitepr-0042")
    svc.approve("sitepr-0042", "project manager")
    svc.write("sitepr-0042")
    assert svc.verify("sitepr-0042").status == SitePRStatus.VERIFIED
    assert svc.store.read("delivery", "D-7", "qty_received") == "10"


def test_recurrence_after_verified_reopens_and_counts(svc):
    approved(svc)
    svc.write("sitepr-0042")
    svc.verify("sitepr-0042")
    pr = svc.reopen("sitepr-0042", "same shortfall on next delivery", recurrence=True)
    assert pr.status == SitePRStatus.REOPENED and pr.recurrence_count == 1


def test_state_survives_restart(tmp_path):
    store = MockRecordStore(tmp_path / "s.db")
    svc = SitePRService(Ledger(tmp_path / "l.db"), store)
    approved(svc)
    again = SitePRService(Ledger(tmp_path / "l.db"), MockRecordStore(tmp_path / "s.db"))
    assert again.get("sitepr-0042").status == SitePRStatus.APPROVED


# -- kill test: a real process dies, a fresh one recovers ---------------------------------------------------------- #

CHILD = textwrap.dedent(
    """
    import os, sys
    sys.path.insert(0, {tests!r})
    from test_sitepr import make_pr
    from amber_lens.sitepr import Ledger, MockRecordStore, SitePRService
    die_at = sys.argv[3]
    def fault(point):
        if point == die_at:
            os._exit(137)  # no cleanup, like kill -9
    svc = SitePRService(Ledger(sys.argv[1]), MockRecordStore(sys.argv[2]), fault=fault)
    svc.draft(make_pr()); svc.submit("sitepr-0042"); svc.approve("sitepr-0042", "project manager")
    if die_at == "after_approve":
        os._exit(137)
    svc.write("sitepr-0042")
    """
)


@pytest.mark.parametrize("die_at", ["after_approve", "after_apply"])
def test_kill_between_approve_and_write_lands_exactly_once(tmp_path, die_at):
    ledger_db, store_db = tmp_path / "l.db", tmp_path / "s.db"
    seed = MockRecordStore(store_db)
    seed.seed("delivery", "D-7", "qty_received", "12")
    code = CHILD.format(tests=str(Path(__file__).parent))
    proc = subprocess.run([sys.executable, "-c", code, str(ledger_db), str(store_db), die_at], check=False)
    assert proc.returncode == 137  # the process really died

    # fresh process state: new objects over the same files
    svc = SitePRService(Ledger(ledger_db), MockRecordStore(store_db))
    assert svc.get("sitepr-0042").status == SitePRStatus.APPROVED  # the ledger still says approved
    assert svc.recover() == ["sitepr-0042"]
    assert svc.get("sitepr-0042").status == SitePRStatus.VERIFIED  # recover also verifies what it wrote
    assert svc.recover() == []  # a second restart does nothing
    assert svc.store.read("delivery", "D-7", "qty_received") == "10"
    assert svc.store.write_count("sitepr-0042:claim:v1") == 1
    assert [e.type for e in svc.ledger.events("sitepr-0042")].count("written") == 1


@pytest.mark.parametrize("role", ["sitepr", "admin", "", "Site Engineer", "site engineer"])
def test_only_a_person_can_approve(svc, role):
    svc.draft(make_pr())
    svc.submit("sitepr-0042")
    with pytest.raises(TransitionError):
        svc.approve("sitepr-0042", role)
    assert svc.get("sitepr-0042").status == SitePRStatus.PENDING_REVIEW


def test_recover_verifies_a_pr_that_died_after_written(svc):
    svc.store.seed("delivery", "D-7", "qty_received", "12")
    svc.draft(make_pr())
    svc.submit("sitepr-0042")
    svc.approve("sitepr-0042", "project manager")
    svc.write("sitepr-0042")  # process "dies" here, before verify
    assert svc.get("sitepr-0042").status == SitePRStatus.WRITTEN
    assert svc.recover() == []
    assert svc.get("sitepr-0042").status == SitePRStatus.VERIFIED
