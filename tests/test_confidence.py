from amber_lens.schemas import BBox, CheckResult, ReadField, ReadStatus, SourceRef
from amber_lens.verdict.confidence import compute_confidence, field_agreement, needs_human

CROP = SourceRef(kind="photo_crop", ref_id="o", bbox=BBox(x=0, y=0, w=1, h=1))


def rf(status=ReadStatus.READ, vision="A", ocr="A", rule=True, inj=False):
    return ReadField(
        name="model_number", value="A" if status == ReadStatus.READ else None, vision_value=vision, ocr_value=ocr,
        format_rule_passed=rule, status=status, source=CROP, injection_flag=inj,
    )


def chk(match="exact", passed=True):
    return CheckResult(name="c", passed=passed, match_type=match)


def test_everything_exact_is_full_confidence():
    assert compute_confidence([chk(), chk()], [rf()], tag_read_ok=True) == 1.0


def test_confidence_ignores_any_model_number_and_is_lower_for_weaker_matches():
    exact = compute_confidence([chk("exact")], [rf()])
    alias = compute_confidence([chk("alias")], [rf()])
    fuzzy = compute_confidence([chk("fuzzy")], [rf()])
    assert exact > alias > fuzzy


def test_fuzzy_with_weak_reading_goes_to_human():
    c = compute_confidence([chk("fuzzy")], [rf(rule=False)])
    assert c < 0.8 and needs_human(c)


def test_missing_data_lowers_completeness():
    c = compute_confidence([chk(), chk(passed=None), chk(), chk()], [rf()])
    assert c == 0.75 and needs_human(c)


def test_disputed_field_drags_agreement_down():
    assert field_agreement([rf(), rf(ReadStatus.DISPUTED)]) == 0.5
    assert field_agreement([rf(vision="A", ocr="B")]) == 0.6


def test_bad_tag_read_lowers_confidence():
    good = compute_confidence([chk()], [rf()], tag_read_ok=True)
    bad = compute_confidence([chk()], [rf()], tag_read_ok=False)
    assert bad < good


def test_injection_flag_caps_confidence_and_forces_human():
    c = compute_confidence([chk()], [rf(inj=True)])
    assert c <= 0.5 and needs_human(c, [rf(inj=True)])


def test_no_checks_or_no_data_is_zero():
    assert compute_confidence([], [rf()]) == 0.0
    assert compute_confidence([chk(passed=None)], [rf()]) == 0.0
