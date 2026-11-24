import pytest

from amber_lens.perception.rules import check_format


@pytest.mark.parametrize(
    "value", ["FX-100A", "M2AA 160 L 4", "0.75KNE4FLG", "3LT50-440/230-Dyn11-23", "120485.00"]
)
def test_model_number_passes(value: str) -> None:
    assert check_format("model_number", value) is True


@pytest.mark.parametrize("value", ["AB", "MOTOR", "460 V", "1760 RPM", "FX_100A!", "A B C D E 1", "X" * 33])
def test_model_number_fails(value: str) -> None:
    assert check_format("model_number", value) is False


@pytest.mark.parametrize(
    "value", ["230/460 V", "208-230/460 V", "415±10% V", "400 Δ V", "480 V / 400 V", "VOLTS 460", "415 +/- 10 % V"]
)
def test_voltage_passes(value: str) -> None:
    assert check_format("voltage", value) is True


@pytest.mark.parametrize("value", ["231/460 V", "7.8/3.9 A", "60 Hz", "V", "460.5 V", "380/420 Δ/Δ V"])
def test_voltage_fails(value: str) -> None:
    assert check_format("voltage", value) is False


@pytest.mark.parametrize("value", ["7.8/3.9 A", "106,0 A", "21-18.8/9.4 A", "12.5 FLA", "7.8/3.9 AMP."])
def test_current_passes(value: str) -> None:
    assert check_format("rated_current", value) is True


@pytest.mark.parametrize("value", ["230 V", "0 A", "9000 A", "3 HP", "A"])
def test_current_fails(value: str) -> None:
    assert check_format("rated_current", value) is False


@pytest.mark.parametrize("value", ["3 HP", "1/2 HP", "1 1/2 HP", "0.75 kW (1.00 HP)", "12.5 KVA", "1,5 kW"])
def test_power_passes(value: str) -> None:
    assert check_format("power", value) is True


@pytest.mark.parametrize("value", ["3", "HP", "230 V", "1760 RPM"])
def test_power_fails(value: str) -> None:
    assert check_format("power", value) is False


@pytest.mark.parametrize("value", ["60 Hz", "50/60 Hz", "6-60 Hz", "50±5% Hz", "60"])
def test_frequency_passes(value: str) -> None:
    assert check_format("frequency", value) is True


@pytest.mark.parametrize("value", ["55 Hz", "1760", "460 V", "Hz"])
def test_frequency_fails(value: str) -> None:
    assert check_format("frequency", value) is False


def test_manufacturer() -> None:
    assert check_format("manufacturer", "WEG") is True
    assert check_format("manufacturer", "Baldor-Reliance") is True
    assert check_format("manufacturer", "ABB") is True
    assert check_format("manufacturer", "A1234") is False
    assert check_format("manufacturer", "X") is False


def test_no_value_means_no_check() -> None:
    assert check_format("voltage", None) is None


def test_unknown_field_raises() -> None:
    with pytest.raises(KeyError):
        check_format("colour", "red")


def test_catalog_number_uses_the_identifier_rule() -> None:
    assert check_format("catalog_number", "HHI150-12-447T") is True
    assert check_format("catalog_number", "460 V") is False


def test_allowed_label_accepts_known_labels_only() -> None:
    from amber_lens.perception.rules import allowed_label

    assert allowed_label("catalog_number", "Cat.  No.") == "Cat. No."
    assert allowed_label("catalog_number", "ORD. NO.") == "ORD. NO."
    assert allowed_label("model_number", "MODEL NO.") == "MODEL NO."
    assert allowed_label("model_number", "CAT. NO.") is None
    assert allowed_label("voltage", "mark approved") is None
    assert allowed_label("manufacturer", "BRAND") is None
    assert allowed_label("voltage", None) is None
    assert allowed_label("voltage", "V" * 30) is None


def test_r3_stray_letter_in_a_rating_hf_020() -> None:
    # hf_020 printed "1.82Y" (star mark glued to the current); it was READ as a current.
    assert check_format("rated_current", "1.82Y") is False
    assert check_format("rated_current", "12.8 A (compressor RLA)") is False
    assert check_format("voltage", "220VΔ/380VY V") is True
    assert check_format("power", "40°C") is False


def test_r2_two_letter_logo_is_not_a_manufacturer_hf_02() -> None:
    # hf_02's efficiency logo "ee" was READ as the manufacturer.
    assert check_format("manufacturer", "ee") is False
    assert check_format("manufacturer", "WEG") is True


def test_attach_power_unit_from_printed_label() -> None:
    from amber_lens.perception.rules import attach_power_unit

    assert attach_power_unit("3", "HP") == "3 HP"
    assert attach_power_unit("1/2", "HP") == "1/2 HP"
    assert attach_power_unit("0.75", "kW") == "0.75 kW"
    assert attach_power_unit("3 HP", "HP") is None
    assert attach_power_unit("3", "VOLTS") is None
    assert attach_power_unit("3", "POWER") is None
    assert attach_power_unit("3", None) is None
