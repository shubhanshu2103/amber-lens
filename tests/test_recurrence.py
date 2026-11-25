import pytest

from amber_lens.schemas import BBox, RecordChange, SitePR, SitePRStatus, SourceRef
from amber_lens.sitepr import Ledger, MockRecordStore, SitePRService
from amber_lens.sitepr.recurrence import report_finding


def crop(ref):
    return [SourceRef(kind="photo_crop", ref_id=ref, bbox=BBox(x=1, y=1, w=5, h=5))]


def finding(pid, new="10", record="D-7", obs="obs-1"):
    return SitePR(
        site_pr_id=pid, verdict_id=f"v-{obs}", finding=f"Delivered {new} vs PO 12", confidence=0.9, evidence=crop(obs),
        changes=[RecordChange(record_kind="delivery", record_id=record, field="qty_received", old_value="12", new_value=new)],
        idempotency_key=f"{pid}:claim:v1",
    )


@pytest.fixture
def svc(tmp_path):
    store = MockRecordStore(tmp_path / "s.db")
    store.seed("delivery", "D-7", "qty_received", "12")
    store.seed("delivery", "D-8", "qty_received", "12")
    return SitePRService(Ledger(tmp_path / "l.db"), store)


def verified(svc, pid="sitepr-0001", **kw):
    svc.draft(finding(pid, **kw))
    svc.submit(pid)
    svc.approve(pid, "project manager")
    svc.write(pid)
    return svc.verify(pid)


def test_the_same_failure_after_a_verified_fix_reopens_it_and_counts_once(svc):
    assert verified(svc).status == SitePRStatus.VERIFIED
    pr = report_finding(svc, finding("sitepr-0002", obs="obs-2"))
    assert pr.site_pr_id == "sitepr-0001"
    assert pr.status == SitePRStatus.REOPENED and pr.recurrence_count == 1
    assert [p.site_pr_id for p in svc.list()] == ["sitepr-0001"]  # no second Site PR for the same issue


def test_a_reopened_pr_carries_the_new_evidence_so_the_reviewer_does_not_approve_stale_proof(svc):
    verified(svc)
    pr = report_finding(svc, finding("sitepr-0002", new="9", obs="obs-2"))
    assert pr.evidence[0].ref_id == "obs-2" and pr.changes[0].new_value == "9" and pr.evidence_hash is None
    assert "9" in pr.finding


def test_the_reopened_pr_gets_a_new_idempotency_key_so_the_fix_can_be_written_again(svc):
    verified(svc)
    pr = report_finding(svc, finding("sitepr-0002", obs="obs-2"))
    assert pr.idempotency_key.endswith(":v2")


def test_a_second_recurrence_counts_twice(svc):
    verified(svc)
    report_finding(svc, finding("sitepr-0002", obs="obs-2"))
    svc.submit("sitepr-0001")
    svc.approve("sitepr-0001", "project manager")
    svc.write("sitepr-0001")
    svc.verify("sitepr-0001")
    pr = report_finding(svc, finding("sitepr-0003", obs="obs-3"))
    assert pr.recurrence_count == 2 and pr.idempotency_key.endswith(":v3")


def test_a_different_record_is_a_new_issue_not_a_recurrence(svc):
    verified(svc)
    pr = report_finding(svc, finding("sitepr-0002", record="D-8"))
    assert pr.site_pr_id == "sitepr-0002" and pr.status == SitePRStatus.DRAFT and pr.recurrence_count == 0


def test_a_fix_that_is_not_verified_yet_is_not_a_recurrence(svc):
    svc.draft(finding("sitepr-0001"))
    svc.submit("sitepr-0001")
    pr = report_finding(svc, finding("sitepr-0002", obs="obs-2"))
    assert pr.site_pr_id == "sitepr-0002" and pr.status == SitePRStatus.DRAFT


def test_a_rejected_or_withdrawn_earlier_pr_is_not_a_recurrence(svc):
    svc.draft(finding("sitepr-0001"))
    svc.self_check("sitepr-0001", "seen elsewhere", withdraw=True)
    assert report_finding(svc, finding("sitepr-0002")).site_pr_id == "sitepr-0002"


def test_the_reopened_pr_can_go_back_through_review(svc):
    verified(svc)
    report_finding(svc, finding("sitepr-0002", obs="obs-2"))
    assert svc.submit("sitepr-0001").status == SitePRStatus.PENDING_REVIEW
