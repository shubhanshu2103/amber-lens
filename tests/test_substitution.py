import pytest
from fakes import FuzzyRecords, free_text, obs, rating, sub_perception, sub_records

from amber_lens.schemas import VerdictCode
from amber_lens.verdict.substitution import check_substitution


def run(records=None, p=None):
    return check_substitution(obs(), p or sub_perception(), records or sub_records())


def check(v, name):
    return next(c for c in v.checks if c.name == name)


def test_nameplate_matches_the_approved_submittal_is_go_with_every_check_sourced():
    v = run()
    assert v.verdict == VerdictCode.GO and not v.needs_human and v.confidence >= 0.8
    assert all(c.passed and c.sources for c in v.checks)
    assert {c.name for c in v.checks} == {
        "model_matches_submittal", "submittal_approved", "rating_voltage", "rating_power"
    }


def test_a_changed_rating_is_deviates_and_says_which():
    v = run(p=sub_perception(power="75 HP"))
    assert v.verdict == VerdictCode.DEVIATES
    c = check(v, "rating_power")
    assert c.passed is False and c.expected == "50 HP" and c.found == "75 HP"


def test_every_planted_rating_change_is_caught():
    for p in (sub_perception(voltage="230 V"), sub_perception(power="40 HP"), sub_perception(voltage="575 V", power="60 HP")):
        assert run(p=p).verdict == VerdictCode.DEVIATES


def test_unit_and_spacing_differences_are_not_a_deviation():
    assert run(p=sub_perception(voltage="460V", power="50hp")).verdict == VerdictCode.GO


def test_an_approved_suffix_passes_as_go_via_alias():
    v = run(records=sub_records(suffixes=["-A"]), p=sub_perception(model="ACME-50HP-A"))
    assert v.verdict == VerdictCode.GO
    assert check(v, "model_matches_submittal").match_type == "alias"


def test_a_suffix_that_is_not_on_the_allowed_list_is_cant_match_never_assumed_harmless():
    v = run(p=sub_perception(model="ACME-50HP-X"))
    assert v.verdict == VerdictCode.CANT_MATCH and v.needs_human


def test_a_rating_change_wins_over_an_unlisted_suffix():
    assert run(p=sub_perception(model="ACME-50HP", power="75 HP")).verdict == VerdictCode.DEVIATES


def test_unread_rating_is_cant_match_not_a_pass():
    v = run(p=sub_perception(power=None))
    assert v.verdict == VerdictCode.CANT_MATCH
    assert check(v, "rating_power").passed is None


def test_unreadable_rating_field_is_cant_match():
    p = sub_perception(power=None)
    p.fields.append(rating("power", None, status="unreadable"))
    assert run(p=p).verdict == VerdictCode.CANT_MATCH


def test_multi_voltage_plate_that_contains_the_approved_voltage_is_ambiguous_not_a_deviation():
    v = run(p=sub_perception(voltage="208-230/460 V"))
    assert v.verdict == VerdictCode.CANT_MATCH
    assert check(v, "rating_voltage").passed is None


@pytest.mark.parametrize("status", ["pending", "rejected", "revise_resubmit"])
def test_no_approved_submittal_means_nothing_to_compare_against(status):
    assert run(records=sub_records(status=status)).verdict == VerdictCode.CANT_MATCH


def test_model_with_no_submittal_is_cant_match():
    assert run(p=sub_perception(model="NOPE-1")).verdict == VerdictCode.CANT_MATCH


def test_a_submittal_rating_we_cannot_map_to_a_nameplate_field_is_cant_match():
    v = run(records=sub_records(ratings={"voltage": "460V", "enclosure": "TEFC"}))
    assert v.verdict == VerdictCode.CANT_MATCH


def test_a_fuzzy_submittal_match_is_never_a_go():
    assert run(records=FuzzyRecords(sub_records())).verdict == VerdictCode.CANT_MATCH


def test_flagged_free_text_forces_a_human():
    v = run(p=sub_perception(extra=[free_text()]))
    assert v.needs_human and "injection_flag" in v.flags


def test_hp_and_amps_are_accepted_as_aliases_of_the_perception_field_names():
    p = sub_perception(power="50 HP")
    p.fields.append(rating("rated_current", "61 A"))
    v = run(records=sub_records(ratings={"hp": "50", "amps": "61"}), p=p)
    assert v.verdict == VerdictCode.GO
    assert {c.name for c in v.checks if c.name.startswith("rating_")} == {"rating_power", "rating_rated_current"}


def test_same_number_in_a_different_unit_is_a_deviation():
    assert run(p=sub_perception(power="50 KW")).verdict == VerdictCode.DEVIATES


def test_a_submittal_with_no_ratings_cannot_be_compared():
    assert run(records=sub_records(ratings={"note": "n/a"})).verdict == VerdictCode.CANT_MATCH
