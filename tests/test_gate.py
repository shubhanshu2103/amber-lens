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


# -- partial deliveries: compare against what is still outstanding, not the whole PO ------------------------------------


def test_a_partial_shipment_that_completes_the_order_is_go():
    [v] = run(ticket([("ACME-50HP", "4", "1")]), gate_records(received={("PO-7", 1): 8}))
    assert v.verdict == VerdictCode.GO
    assert check(v, "qty_matches_po").expected == "4"


def test_more_than_is_outstanding_is_over_even_if_below_the_full_po_quantity():
    [v] = run(ticket([("ACME-50HP", "6", "1")]), gate_records(received={("PO-7", 1): 8}))
    assert v.verdict == VerdictCode.OVER


def test_less_than_is_outstanding_is_short():
    [v] = run(ticket([("ACME-50HP", "2", "1")]), gate_records(received={("PO-7", 1): 8}))
    assert v.verdict == VerdictCode.SHORT and check(v, "qty_matches_po").expected == "4"


def test_a_line_that_is_already_fully_received_makes_any_new_delivery_over():
    [v] = run(ticket([("ACME-50HP", "1", "1")]), gate_records(received={("PO-7", 1): 12}))
    assert v.verdict == VerdictCode.OVER


# -- split lines, the current ticket, odd quantities ---------------------------------------------------------------------


def test_two_rows_for_the_same_po_line_are_compared_as_one_summed_quantity():
    vs = run(ticket([("ACME-50HP", "6", "1"), ("ACME-50HP", "6", "1")]))
    assert len(vs) == 1 and vs[0].verdict == VerdictCode.GO
    assert check(vs[0], "qty_matches_po").found == "12"


@pytest.mark.parametrize("second,code", [("7", VerdictCode.OVER), ("4", VerdictCode.SHORT)])
def test_a_split_line_that_adds_up_wrong_is_short_or_over_once(second, code):
    vs = run(ticket([("ACME-50HP", "6", "1"), ("ACME-50HP", second, "1")]))
    assert [v.verdict for v in vs] == [code]


def test_one_unread_row_of_a_split_line_makes_the_whole_line_cant_match():
    vs = run(ticket([("ACME-50HP", "6", "1"), ("ACME-50HP", None, "1")]))
    assert [v.verdict for v in vs] == [VerdictCode.CANT_MATCH]


def test_receipts_of_the_ticket_being_checked_are_left_out_so_a_rescan_gives_the_same_answer():
    records = gate_records(receipts={("PO-7", 1): [("T-0", 8), ("T-1", 4)]})
    [v] = run(ticket([("ACME-50HP", "4", "1")], ticket_id="T-1"), records)
    assert v.verdict == VerdictCode.GO and records.asked == ["T-1"]
    [other] = run(ticket([("ACME-50HP", "4", "1")], ticket_id="T-2"), records)  # a different ticket after all 12 arrived
    assert other.verdict == VerdictCode.OVER


def test_a_crate_label_has_no_ticket_id_to_exclude():
    records = gate_records()
    run(crate_label(), records)
    assert records.asked == [None]


def test_already_over_received_is_sent_to_a_person_not_clamped_to_zero():
    [v] = run(ticket([("ACME-50HP", "1", "1")]), gate_records(received={("PO-7", 1): 14}))
    assert v.verdict == VerdictCode.CANT_MATCH and v.needs_human


def test_a_quantity_of_zero_is_sent_to_a_person():
    assert run(ticket([("ACME-50HP", "0", "1")]))[0].verdict == VerdictCode.CANT_MATCH


@pytest.mark.parametrize("qty", ["1\u00b2", "\u0661\u0662", "-3", "1.5"])
def test_a_quantity_that_is_not_plain_digits_is_cant_match_not_a_crash(qty):
    assert run(ticket([("ACME-50HP", qty, "1")]))[0].verdict == VerdictCode.CANT_MATCH


def test_sources_are_not_repeated_in_the_verdict_or_the_site_pr():
    [v] = run(ticket([("ACME-50HP", "5", "1"), ("ACME-50HP", "5", "1")]))
    keys = [s.model_dump_json() for s in v.sources]
    assert len(keys) == len(set(keys))
    pr = draft_gate_site_pr(v, "sitepr-9")
    assert len({s.model_dump_json() for s in pr.evidence}) == len(pr.evidence)


def test_a_flagged_free_text_line_caps_confidence():
    assert run(ticket(extra=[free_text()]))[0].confidence <= 0.5
