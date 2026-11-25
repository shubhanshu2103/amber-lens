from amber_lens.perception.locate import locate, match_key, strict_key, value_parts
from amber_lens.perception.ocr import OcrLine, OcrWord, union_bbox
from amber_lens.schemas import BBox


def _line(index: int, *texts: str, pass_id: str = "psm11-gray") -> OcrLine:
    words = tuple(
        OcrWord(text=t, conf=90.0, bbox=BBox(x=10 + 60 * i, y=20 * index, w=50, h=15), line_key=(1, 1, index))
        for i, t in enumerate(texts)
    )
    return OcrLine(text=" ".join(texts), bbox=union_bbox([w.bbox for w in words]), words=words, pass_id=pass_id)


LINES = [
    _line(0, "MODEL", "NO.", "DIO034PCI"),
    _line(1, "VOLTS", "230/460", "AMP.7.8/3.9"),
    _line(2, "M2AA", "160", "L", "4"),
    _line(3, "Input:", "480V", "15,5A"),
    _line(4, "Output:", "400V", "18,0A"),
    _line(5, "15", "kW", "Hz", "50", pass_id="psm6-binary"),
]


def test_match_key_folds_confusables_dashes_comma_and_space() -> None:
    assert match_key("DI0034PCI") == match_key("DIO034PCI")
    assert match_key("DI0034PCI", fold=False) != match_key("DIO034PCI", fold=False)
    assert match_key("208–230/460") == match_key("208-230/460")
    assert match_key("15,5") == match_key("15.5")
    assert match_key("M2AA 160 L 4") == match_key("M2AA160L4")


def test_value_parts_strip_units_and_split_input_output() -> None:
    assert value_parts("voltage", "230/460 V") == ["230/460"]
    assert value_parts("voltage", "480 V (input) / 400 V (output)") == ["480", "400"]
    assert value_parts("rated_current", "12.8 A (compressor RLA)") == ["12.8"]
    assert value_parts("catalog_number", "R22-1/2B / 2501") == [match_key("r22-1/2b/2501")]
    assert value_parts("voltage", "V") == []


def test_strict_key_ignores_units_but_not_glyphs() -> None:
    assert strict_key("voltage", "230/460 V") == strict_key("voltage", "230/460")
    assert strict_key("model_number", "DI0034PCI") != strict_key("model_number", "DIO034PCI")


def test_locates_model_and_reports_glyph_difference() -> None:
    hit = locate("model_number", "DI0034PCI", LINES)
    assert hit.bbox == BBox(x=130, y=0, w=50, h=15)
    assert hit.ocr_text == "DIO034PCI"
    assert hit.exact is False
    assert locate("model_number", "DIO034PCI", LINES).exact is True


def test_locates_multi_word_model() -> None:
    hit = locate("model_number", "M2AA 160 L 4", LINES)
    assert hit.bbox == BBox(x=10, y=40, w=230, h=15)
    assert hit.exact is True


def test_locates_value_glued_to_its_label() -> None:
    hit = locate("rated_current", "7.8/3.9 A", LINES)
    assert hit.bbox == BBox(x=130, y=20, w=50, h=15)
    assert hit.exact is True


def test_locates_each_part_and_unions_boxes() -> None:
    hit = locate("rated_current", "15.5 A / 18.0 A", LINES)
    assert hit.bbox == BBox(x=130, y=60, w=50, h=35)
    assert hit.ocr_text == "15,5A / 18,0A"
    assert hit.exact is True


def test_short_rating_needs_its_unit_on_the_line() -> None:
    assert locate("rated_current", "15 A", LINES) is None
    hit = locate("frequency", "50 Hz", LINES)
    assert hit is not None and hit.pass_id == "psm6-binary"


def test_invented_value_is_not_located() -> None:
    assert locate("model_number", "R22-1/2B-2501-A", LINES) is None
    assert locate("voltage", "380/400 V", LINES) is None


def test_partial_match_is_not_enough() -> None:
    assert locate("voltage", "460 V", LINES) is None
    assert locate("voltage", "480 V / 999 V", LINES) is None


def test_glued_prefix_may_be_a_folded_label_but_never_another_number() -> None:
    lines = [_line(0, "CAT.NO.HHI150-12"), _line(1, "Input:480V15,5A")]
    assert locate("catalog_number", "HHI150-12", lines).exact is True
    assert locate("rated_current", "15.5 A", lines) is None
