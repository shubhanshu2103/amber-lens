import pytest
from fakes import FuzzyRecords, free_text, obs, rating, sub_perception, sub_records

from amber_lens.schemas import VerdictCode
from amber_lens.verdict.substitution import check_substitution, compare_rating


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


def test_a_rating_change_wins_over_an_allowed_suffix():
    v = run(records=sub_records(suffixes=["-A"]), p=sub_perception(model="ACME-50HP-A", power="75 HP"))
    assert v.verdict == VerdictCode.DEVIATES


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


# -- printed formats: each is a match or "cannot tell", never a false mismatch ---------------------------------------


@pytest.mark.parametrize("approved,found,expected", [
    ("15.5 A", "15,5 A", True),                  # decimal comma
    ("460V", "230 V / 460 V", None),             # multi-rating plate containing the approved value
    ("400 V", "400 \u0394 / 690 Y", None),        # delta / wye wiring letters are not units
    ("460V", "460 VAC", True),                   # VAC is volts
    ("230V", "230 VDC", True),
])
def test_printed_formats_are_a_match_or_undecided(approved, found, expected):
    assert compare_rating(approved, found) is expected


def test_a_second_unit_in_brackets_is_not_a_mismatch():
    assert compare_rating("1 HP", "1.0 HP (0.75 kW)") is not False
    assert compare_rating("0.75 kW", "1.0 HP (0.75 kW)") is not False


@pytest.mark.parametrize("approved,found", [
    ("60 Hz", "50 Hz"), ("460 V", "230 V"), ("50 HP", "75 HP"), ("50 HP", "50 kW"), ("15.5 A", "16,5 A"),
])
def test_real_changes_stay_mismatches(approved, found):
    assert compare_rating(approved, found) is False


def test_a_missing_unit_in_the_approved_value_is_taken_from_the_key():
    assert compare_rating("50", "50 kW", key="hp") is False
    assert compare_rating("50", "50 HP", key="hp") is True
    assert compare_rating("0.75", "0.75 kW", key="kw") is True
    assert compare_rating("61", "61 A", key="amps") is True


def test_hp_and_kw_both_listed_for_one_plate_value_pass_only_if_both_do_and_deviate_only_if_both_fail():
    both = run(records=sub_records(ratings={"hp": "1", "kw": "0.75"}), p=sub_perception(voltage=None, power="1 HP (0.75 kW)"))
    assert both.verdict == VerdictCode.GO and [c.name for c in both.checks if c.name.startswith("rating_")] == ["rating_power"]
    one = run(records=sub_records(ratings={"hp": "1", "kw": "0.75"}), p=sub_perception(voltage=None, power="1 HP"))
    assert one.verdict == VerdictCode.CANT_MATCH
    changed = run(records=sub_records(ratings={"hp": "50", "kw": "37"}), p=sub_perception(voltage=None, power="75 HP"))
    assert changed.verdict == VerdictCode.DEVIATES


@pytest.mark.parametrize("make", [lambda: sub_records(status="pending"), lambda: FuzzyRecords(sub_records())])
def test_ratings_are_only_compared_against_an_approved_exact_submittal(make):
    v = run(records=make(), p=sub_perception(power="75 HP"))
    assert v.verdict == VerdictCode.CANT_MATCH
    assert not any(c.name.startswith("rating_") for c in v.checks)


def test_a_rating_on_the_plate_that_the_submittal_does_not_list_is_not_compared():
    p = sub_perception()
    p.fields.append(rating("frequency", "50 Hz"))
    assert run(p=p).verdict == VerdictCode.GO  # deliberate: the approved list defines what is checked


def test_a_flagged_free_text_line_caps_confidence():
    assert run(p=sub_perception(extra=[free_text()])).confidence <= 0.5


# -- approved ratings that list several values (real rows from Project Alpha) ----------------------------------------


@pytest.mark.parametrize("approved,found,key", [
    ("208–230/460 V", "208-230/460 V", "voltage"),   # en dash in the record, hyphen on the plate
    ("208–230/460 V", "208-230/460", "voltage"),     # unit missing on the plate
    ("180/166/83 A", "180/166/83 A", "rated_current"),
    ("230/460 V", "230/460 V", "voltage"),
    ("2/1 A", "2/1 A", "rated_current"),
])
def test_an_approved_multi_value_rating_matches_the_same_plate_text(approved, found, key):
    assert compare_rating(approved, found, key) is True


@pytest.mark.parametrize("approved,found", [
    ("230/460 V", "230/575 V"),      # a different second voltage is a different motor
    ("230/460 V", "115/230 V"),
    ("2/1 A", "3/1.5 A"),
])
def test_a_multi_value_rating_with_different_values_is_a_mismatch(approved, found):
    assert compare_rating(approved, found) is False


@pytest.mark.parametrize("approved,found", [
    ("230/460 V", "460 V"),          # the plate shows only part of what was approved
    ("230/460 V", "208-230/460 V"),  # the plate shows more than was approved
])
def test_a_multi_value_rating_the_plate_only_partly_shows_is_undecided(approved, found):
    assert compare_rating(approved, found) is None


def test_a_real_multi_voltage_motor_can_be_a_go():
    records = sub_records(ratings={"voltage": "208–230/460 V", "power": "75 HP"})
    assert run(records=records, p=sub_perception(voltage="208-230/460", power="75 HP")).verdict == VerdictCode.GO
