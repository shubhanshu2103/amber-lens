from datetime import timedelta

import pytest

from amber_lens.schemas import BBox, RecordChange, Sighting, SitePR, SitePRStatus, SourceRef, utcnow
from amber_lens.sitepr import Ledger, MockRecordStore, SitePRService
from amber_lens.sitepr.selfcheck import ItemRef, self_check_claim

NOW = utcnow()
EVID = [SourceRef(kind="photo_crop", ref_id="obs-1", bbox=BBox(x=1, y=1, w=5, h=5))]


class FakeSightings:
    """Stands in for the sightings table (#14): every sighting of a model, newest or oldest in any order."""

    def __init__(self, *sightings):
        self.rows = list(sightings)

    def sightings_for_model(self, model_number):
        return [s for s in self.rows if s.model_number == model_number]


def seen(days_ago, room="WH-1", tag=None, model="ACME-50HP", obs="obs-77"):
    return Sighting(model_number=model, equipment_tag=tag, room_tag=room, observation_id=obs,
                    seen_at=NOW - timedelta(days=days_ago))


def claim(pid="sitepr-0001", field="missing", rid="P-101"):
    return SitePR(
        site_pr_id=pid, verdict_id="v-1", finding="Pump P-101 is not in RM-201", confidence=0.9, evidence=EVID,
        changes=[RecordChange(record_kind="claim", record_id=rid, field=field, old_value=None, new_value="1")],
        idempotency_key=f"{pid}:claim:v1",
    )


@pytest.fixture
def svc(tmp_path):
    return SitePRService(Ledger(tmp_path / "l.db"), MockRecordStore(tmp_path / "s.db"))


def run(svc, sightings, pid="sitepr-0001", item=None, **kw):
    item = item or ItemRef("ACME-50HP")
    svc.draft(claim(pid))
    return self_check_claim(svc, pid, item, sightings, now=NOW, **kw)


def test_an_item_seen_in_the_warehouse_two_days_ago_withdraws_the_claim_and_cites_the_sighting(svc):
    pr = run(svc, FakeSightings(seen(2)))
    assert pr.status == SitePRStatus.WITHDRAWN
    assert "WH-1" in pr.self_check_note and "obs-77" in pr.self_check_note
    withdrawn = next(e for e in svc.ledger.events("sitepr-0001") if e.type == "withdrawn")
    assert withdrawn.payload["sighting"]["observation_id"] == "obs-77"


def test_a_sighting_older_than_the_window_does_not_withdraw(svc):
    pr = run(svc, FakeSightings(seen(9)))
    assert pr.status == SitePRStatus.DRAFT and "no sighting" in pr.self_check_note


def test_the_window_is_configurable(svc):
    assert run(svc, FakeSightings(seen(9)), window_days=14).status == SitePRStatus.WITHDRAWN


def test_no_sightings_at_all_leaves_the_claim_to_be_reviewed(svc):
    pr = run(svc, FakeSightings())
    assert pr.status == SitePRStatus.DRAFT and pr.self_check_note


def test_a_sighting_from_the_future_is_ignored(svc):
    assert run(svc, FakeSightings(seen(-3))).status == SitePRStatus.DRAFT


def test_a_different_unit_of_the_same_model_does_not_withdraw_a_claim_about_a_tagged_item(svc):
    pr = run(svc, FakeSightings(seen(1, tag="P-999")), item=ItemRef("ACME-50HP", "P-101"))
    assert pr.status == SitePRStatus.DRAFT


def test_the_same_tag_withdraws(svc):
    assert run(svc, FakeSightings(seen(1, tag="P-101")), item=ItemRef("ACME-50HP", "P-101")).status == SitePRStatus.WITHDRAWN


def test_a_model_only_match_says_so_in_the_note(svc):
    pr = run(svc, FakeSightings(seen(1)))
    assert "model only" in pr.self_check_note


def test_a_sighting_of_another_model_is_ignored(svc):
    assert run(svc, FakeSightings(seen(1, model="OTHER-1"))).status == SitePRStatus.DRAFT


def test_the_most_recent_sighting_is_the_one_cited(svc):
    pr = run(svc, FakeSightings(seen(5, obs="obs-old"), seen(1, obs="obs-new")))
    assert "obs-new" in pr.self_check_note and "obs-old" not in pr.self_check_note


# -- do not draft a re-order that is already open -------------------------------------------------------------------------


def open_claim(svc, pid, status_steps):
    svc.draft(claim(pid, field="reorder"))
    svc.self_check(pid, "ok")
    if status_steps >= 1:
        svc.submit(pid)
    if status_steps >= 2:
        svc.approve(pid, "project manager")


def test_a_reorder_that_is_already_pending_withdraws_the_new_draft_and_cites_it(svc):
    open_claim(svc, "sitepr-0001", 1)
    svc.draft(claim("sitepr-0002", field="reorder"))
    pr = self_check_claim(svc, "sitepr-0002", ItemRef("ACME-50HP"), FakeSightings(), now=NOW)
    assert pr.status == SitePRStatus.WITHDRAWN and "sitepr-0001" in pr.self_check_note


def test_an_approved_reorder_also_counts_as_open(svc):
    open_claim(svc, "sitepr-0001", 2)
    svc.draft(claim("sitepr-0002", field="reorder"))
    assert self_check_claim(svc, "sitepr-0002", ItemRef("ACME-50HP"), FakeSightings(), now=NOW).status == SitePRStatus.WITHDRAWN


def test_a_rejected_or_withdrawn_reorder_does_not_block_a_new_one(svc):
    svc.draft(claim("sitepr-0001", field="reorder"))
    svc.self_check("sitepr-0001", "x", withdraw=True)
    svc.draft(claim("sitepr-0002", field="reorder"))
    assert self_check_claim(svc, "sitepr-0002", ItemRef("ACME-50HP"), FakeSightings(), now=NOW).status == SitePRStatus.DRAFT


def test_a_reorder_for_a_different_item_does_not_block(svc):
    open_claim(svc, "sitepr-0001", 1)
    svc.draft(claim("sitepr-0002", field="reorder", rid="P-202"))
    assert self_check_claim(svc, "sitepr-0002", ItemRef("ACME-50HP"), FakeSightings(), now=NOW).status == SitePRStatus.DRAFT


def test_two_drafts_for_the_same_reorder_do_not_withdraw_each_other(svc):
    svc.draft(claim("sitepr-0001", field="reorder"))
    svc.draft(claim("sitepr-0002", field="reorder"))
    first = self_check_claim(svc, "sitepr-0001", ItemRef("ACME-50HP"), FakeSightings(), now=NOW)
    second = self_check_claim(svc, "sitepr-0002", ItemRef("ACME-50HP"), FakeSightings(), now=NOW)
    assert first.status == SitePRStatus.DRAFT and second.status == SitePRStatus.WITHDRAWN
