from amber_lens.perception.scoring import Outcome, comparison_key, score_field, tally, values_agree


def test_key_ignores_case_space_and_own_unit() -> None:
    assert comparison_key("voltage", "230/460 V") == comparison_key("voltage", "230 / 460")
    assert comparison_key("rated_current", "12.8 A (compressor RLA)") == "12.8"
    assert comparison_key("frequency", "60 Hz") == "60"
    assert comparison_key("model_number", "M2AA 160 L 4") == "m2aa160l4"


def test_key_folds_dash_style_and_decimal_comma() -> None:
    assert comparison_key("voltage", "208–230/460 V") == comparison_key("voltage", "208-230/460 V")
    assert comparison_key("rated_current", "15,5 A / 18,0 A") == comparison_key("rated_current", "15.5A / 18.0A")
    assert comparison_key("voltage", "230/460") != comparison_key("voltage", "230,460")


def test_key_keeps_other_units_and_numbers() -> None:
    assert comparison_key("power", "3 HP") != comparison_key("power", "3 kW")
    assert comparison_key("voltage", "400 Δ V") != comparison_key("voltage", "400 V")


def test_power_accepts_either_printed_unit() -> None:
    assert values_agree("power", "1.0 HP", "1.0 HP (0.75 kW)")
    assert values_agree("power", "0.75 kW", "1.0 HP (0.75 kW)")
    assert not values_agree("power", "1 HP", "1.0 HP (0.75 kW)")


def test_manufacturer_containment() -> None:
    assert values_agree("manufacturer", "WEG", "WEG Electric")
    assert not values_agree("manufacturer", "ABB", "Sterling Electric")
    assert not values_agree("manufacturer", "...", "Sterling Electric")


def test_outcomes() -> None:
    assert score_field("voltage", "460 V", "460 V") is Outcome.CORRECT
    assert score_field("voltage", "480 V", "460 V") is Outcome.WRONG
    assert score_field("voltage", "460 V", None) is Outcome.EXTRA
    assert score_field("voltage", None, "460 V") is Outcome.MISSED
    assert score_field("voltage", None, None) is Outcome.ABSTAINED_OK


def test_tally_reports_zero_counts() -> None:
    counts = tally([Outcome.CORRECT, Outcome.CORRECT])
    assert counts[Outcome.CORRECT] == 2
    assert counts[Outcome.WRONG] == 0
