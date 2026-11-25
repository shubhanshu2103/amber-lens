import pytest
from fakes import FakeRecords, FuzzyRecords, free_text, good_records, model_field, obs, perception

from amber_lens.schemas import POLine, ReadStatus, ScheduleItem, VerdictCode
from amber_lens.verdict.preinstall import check_pre_install


def run(records=None, o=None, p=None):
    return check_pre_install(o or obs(), p or perception(), records or good_records())


def check(v, name):
    return next(c for c in v.checks if c.name == name)


def test_everything_matches_is_go_with_every_check_sourced():
    v = run()
    assert v.verdict == VerdictCode.GO
    assert not v.needs_human and v.confidence >= 0.8
    assert [c.name for c in v.checks] == [
        "model_in_schedule", "room_matches_schedule", "model_matches_po", "submittal_approved"
    ]
    assert all(c.passed and c.sources for c in v.checks)


def test_wrong_room_is_hold_and_says_where_it_belongs():
    v = run(o=obs(room_tag="RM-305"))
    assert v.verdict == VerdictCode.HOLD
    room = check(v, "room_matches_schedule")
    assert room.passed is False and room.expected == "RM-201" and room.found == "RM-305"


def test_unapproved_submittal_is_hold():
    v = run(records=good_records(sub_status="pending"))
    assert v.verdict == VerdictCode.HOLD
    assert check(v, "submittal_approved").passed is False


def test_approved_as_noted_counts_as_approved():
    assert run(records=good_records(sub_status="approved_as_noted")).verdict == VerdictCode.GO


def test_no_po_line_is_hold():
    v = run(records=good_records(with_po=False))
    assert v.verdict == VerdictCode.HOLD
    assert check(v, "model_matches_po").passed is False


def test_unreadable_model_is_cant_match_and_goes_to_a_human():
    v = run(p=perception(model_field(status=ReadStatus.UNREADABLE)))
    assert v.verdict == VerdictCode.CANT_MATCH
    assert v.needs_human and "unreadable_field" in v.flags


def test_room_tag_not_scanned_is_never_go():
    v = run(o=obs(room_tag=None))
    assert v.verdict == VerdictCode.CANT_MATCH
    assert check(v, "room_matches_schedule").passed is None
    assert v.needs_human


def test_tag_that_did_not_read_cleanly_is_never_go():
    assert run(p=perception(tag_read_ok=False)).verdict == VerdictCode.CANT_MATCH


def test_model_not_on_schedule_is_cant_match_not_a_guess():
    v = run(p=perception(model_field("OTHER-99")))
    assert v.verdict == VerdictCode.CANT_MATCH
    assert check(v, "model_in_schedule").passed is None


def test_known_failure_beats_missing_data():
    v = run(records=good_records(sub_status="rejected"), o=obs(room_tag=None))
    assert v.verdict == VerdictCode.HOLD


def test_allowed_suffix_passes_as_go_with_lower_confidence():
    exact = run(records=good_records(suffixes=["-A"]))
    alias = run(records=good_records(suffixes=["-A"]), p=perception(model_field("ACME-50HP-A")))
    assert alias.verdict == VerdictCode.GO
    assert check(alias, "model_in_schedule").match_type == "alias"
    assert alias.confidence < exact.confidence


def test_injection_flag_forces_human_review_and_is_reported():
    v = run(p=perception(model_field(inj=True)))
    assert v.needs_human and "injection_flag" in v.flags


def test_model_on_two_rows_uses_the_room_to_pick_one():
    records = good_records()
    records.schedule.append(
        ScheduleItem(equipment_tag="P-102", model_number="ACME-50HP", room_tag="RM-305", drawing_ref="M-102")
    )
    assert run(records=records, o=obs(room_tag="RM-305")).verdict == VerdictCode.HOLD  # P-102's PO line is missing
    assert check(run(records=records, o=obs(room_tag="RM-305")), "model_matches_po").passed is False


def test_model_on_two_rows_without_a_room_cannot_be_resolved():
    records = good_records()
    records.schedule.append(
        ScheduleItem(equipment_tag="P-102", model_number="ACME-50HP", room_tag="RM-305", drawing_ref="M-102")
    )
    assert run(records=records, o=obs(room_tag=None)).verdict == VerdictCode.CANT_MATCH


def test_empty_records_object_is_cant_match():
    assert run(records=FakeRecords()).verdict == VerdictCode.CANT_MATCH


@pytest.mark.parametrize("only", [("schedule",), ("po",), ("submittal",), ("schedule", "po", "submittal")])
def test_a_fuzzy_match_is_never_a_go(only):
    v = run(records=FuzzyRecords(good_records(), only))
    assert v.verdict == VerdictCode.CANT_MATCH
    assert v.needs_human


def test_flagged_free_text_line_forces_a_human_even_with_a_clean_model_number():
    v = run(p=perception(extra=[free_text()]))
    assert "injection_flag" in v.flags and v.needs_human


def test_unflagged_free_text_does_not_trigger_review():
    v = run(p=perception(extra=[free_text(inj=False)]))
    assert v.verdict == VerdictCode.GO and not v.needs_human


def test_a_read_catalog_number_alone_can_match():
    p = perception(model_field(name="catalog_number"))
    p.fields.append(model_field(status=ReadStatus.UNREADABLE))
    assert run(p=p).verdict == VerdictCode.GO


def test_catalog_number_is_tried_before_model_number():
    p = perception(model_field("ACME-50HP", name="catalog_number"))
    p.fields.append(model_field("OTHER-99"))  # the model number is not on the schedule, the catalog number is
    assert run(p=p).verdict == VerdictCode.GO


def test_model_number_is_used_when_the_catalog_number_is_not_on_the_schedule():
    p = perception(model_field("OTHER-99", name="catalog_number"))
    p.fields.append(model_field())
    assert run(p=p).verdict == VerdictCode.GO


def test_po_line_without_an_equipment_tag_matches_by_model():
    records = good_records()
    records.po = [POLine(po_number="PO-7", line=1, equipment_tag=None, model_number="ACME-50HP", description="pump",
                         qty=1, submittal_id="SUB-9")]
    v = run(records=records)
    assert v.verdict == VerdictCode.GO
