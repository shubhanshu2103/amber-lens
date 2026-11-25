import pytest
from fakes import GateRecords, crate_label, free_text, gate_records, obs, ticket

from amber_lens.schemas import SitePRStatus, VerdictCode
from amber_lens.verdict.gate import check_gate, draft_gate_site_pr


def run(p, records=None):
    return check_gate(obs(kind="delivery_ticket"), p, records or gate_records())


def check(v, name):
    return next(c for c in v.checks if c.name == name)


def test_matching_quantity_is_go_with_every_check_sourced():
    [v] = run(ticket())
    assert v.verdict == VerdictCode.GO and not v.needs_human and v.confidence >= 0.8
    assert all(c.passed and c.sources for c in v.checks)


def test_fewer_delivered_than_ordered_is_short():
    [v] = run(ticket([("ACME-50HP", "10", "1")]))
    assert v.verdict == VerdictCode.SHORT
    q = check(v, "qty_matches_po")
    assert q.passed is False and q.expected == "12" and q.found == "10"


def test_more_delivered_than_ordered_is_over():
    [v] = run(ticket([("ACME-50HP", "14", "1")]))
    assert v.verdict == VerdictCode.OVER


def test_each_ticket_line_gets_its_own_verdict():
    vs = run(ticket([("ACME-50HP", "12", "1"), ("VALVE-2", "3", "2")]))
    assert [v.verdict for v in vs] == [VerdictCode.GO, VerdictCode.SHORT]
    assert len({v.verdict_id for v in vs}) == 2


def test_an_unread_quantity_is_cant_match_never_zero():
    [v] = run(ticket([("ACME-50HP", None, "1")]))
    assert v.verdict == VerdictCode.CANT_MATCH and v.needs_human
    assert check(v, "qty_matches_po").passed is None


def test_a_po_line_we_do_not_have_is_cant_match():
    assert run(ticket([("ACME-50HP", "12", "9")]))[0].verdict == VerdictCode.CANT_MATCH


def test_unreadable_po_number_is_cant_match():
    assert run(ticket(po=None))[0].verdict == VerdictCode.CANT_MATCH


def test_a_different_model_on_the_line_is_cant_match_even_when_the_quantity_is_off():
    [v] = run(ticket([("OTHER-99", "10", "1")]))
    assert v.verdict == VerdictCode.CANT_MATCH


def test_spacing_and_dash_differences_in_the_model_still_match():
    [v] = run(ticket([("acme 50hp", "12", "1")]))
    assert v.verdict == VerdictCode.GO and check(v, "model_matches_po").match_type == "normalised"


def test_a_crate_label_is_checked_like_a_single_ticket_line():
    assert run(crate_label())[0].verdict == VerdictCode.GO
    assert run(crate_label(qty="11"))[0].verdict == VerdictCode.SHORT


def test_a_ticket_with_no_readable_lines_is_one_cant_match():
    vs = run(ticket(lines=[]))
    assert len(vs) == 1 and vs[0].verdict == VerdictCode.CANT_MATCH


def test_flagged_text_on_the_document_forces_a_human_and_is_reported():
    [v] = run(ticket(extra=[free_text()]))
    assert v.needs_human and "injection_flag" in v.flags


def test_empty_records_is_cant_match():
    assert run(ticket(), GateRecords())[0].verdict == VerdictCode.CANT_MATCH


# -- Site PR drafting ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("qty,field,diff", [("10", "short_qty", "2"), ("15", "over_qty", "3")])
def test_short_and_over_draft_a_site_pr_with_evidence(qty, field, diff):
    [v] = run(ticket([("ACME-50HP", qty, "1")]))
    pr = draft_gate_site_pr(v, "sitepr-0042")
    assert pr.status == SitePRStatus.DRAFT and pr.verdict_id == v.verdict_id
    assert pr.idempotency_key == "sitepr-0042:claim:v1"
    [change] = pr.changes
    assert (change.record_kind, change.record_id, change.field, change.new_value) == ("claim", "PO-7:1", field, diff)
    assert pr.evidence and {s.kind for s in pr.evidence} >= {"photo_crop", "po_line"}
    assert pr.confidence == v.confidence


def test_go_and_cant_match_draft_nothing():
    assert draft_gate_site_pr(run(ticket())[0], "sitepr-1") is None
    assert draft_gate_site_pr(run(ticket([("ACME-50HP", None, "1")]))[0], "sitepr-2") is None
