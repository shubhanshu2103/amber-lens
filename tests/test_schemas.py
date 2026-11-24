"""Contract tests: these encode the trust rules, so they must never be relaxed casually."""

import pytest
from pydantic import ValidationError

from amber_lens.schemas import (
    BBox,
    CheckResult,
    ReadField,
    ReadStatus,
    SitePRStatus,
    SourceRef,
    Verdict,
    VerdictCode,
    can_transition,
)

PO_SRC = SourceRef(kind="po_line", ref_id="PO-4471", detail="line 7")
CROP = SourceRef(kind="photo_crop", ref_id="obs-001", bbox=BBox(x=10, y=20, w=100, h=30))


def _verdict(code, checks):
    return Verdict(
        verdict_id="v-1",
        observation_id="obs-001",
        check_type="pre_install",
        verdict=code,
        checks=checks,
        confidence=0.9,
        needs_human=False,
        explanation="test",
        sources=[CROP],
    )


def test_photo_crop_requires_bbox():
    with pytest.raises(ValidationError):
        SourceRef(kind="photo_crop", ref_id="obs-001")


def test_unread_field_cannot_carry_a_value():
    with pytest.raises(ValidationError):
        ReadField(name="sccr", value="65kA", status=ReadStatus.DISPUTED, source=CROP)


def test_read_field_ok():
    f = ReadField(name="sccr", value="65kA", status=ReadStatus.READ, source=CROP)
    assert f.value == "65kA"


def test_go_requires_every_check_passed_and_sourced():
    ok = CheckResult(name="model_matches_po", passed=True, sources=[PO_SRC], match_type="exact")
    unsourced = CheckResult(name="room_matches_schedule", passed=True, sources=[])
    missing_data = CheckResult(name="submittal_approved", passed=None, sources=[PO_SRC])

    assert _verdict(VerdictCode.GO, [ok]).verdict == VerdictCode.GO
    with pytest.raises(ValidationError):
        _verdict(VerdictCode.GO, [ok, unsourced])
    with pytest.raises(ValidationError):
        _verdict(VerdictCode.GO, [ok, missing_data])
    with pytest.raises(ValidationError):
        _verdict(VerdictCode.GO, [])


def test_non_go_verdict_allows_failed_checks():
    bad = CheckResult(name="room_matches_schedule", passed=False, expected="L4-PLANT", found="L3-PLANT", sources=[PO_SRC])
    assert _verdict(VerdictCode.HOLD, [bad]).verdict == VerdictCode.HOLD


def test_sitepr_cannot_skip_approval():
    assert can_transition(SitePRStatus.PENDING_REVIEW, SitePRStatus.APPROVED)
    assert not can_transition(SitePRStatus.DRAFT, SitePRStatus.WRITTEN)
    assert not can_transition(SitePRStatus.PENDING_REVIEW, SitePRStatus.WRITTEN)
    assert not can_transition(SitePRStatus.REJECTED, SitePRStatus.APPROVED)


def test_verified_sitepr_can_reopen_on_recurrence():
    assert can_transition(SitePRStatus.VERIFIED, SitePRStatus.REOPENED)


def test_unreadable_field_needs_no_source_but_read_field_does():
    ReadField(name="sccr", value=None, status=ReadStatus.UNREADABLE)
    with pytest.raises(ValidationError):
        ReadField(name="sccr", value="65kA", status=ReadStatus.READ)


def test_verdict_must_fit_its_check_type():
    with pytest.raises(ValidationError):
        Verdict(
            verdict_id="v-2", observation_id="o", check_type="substitution", verdict=VerdictCode.SHORT,
            checks=[], confidence=0.9, needs_human=False, explanation="x", sources=[],
        )


def test_low_confidence_requires_human():
    with pytest.raises(ValidationError):
        Verdict(
            verdict_id="v-3", observation_id="o", check_type="gate", verdict=VerdictCode.CANT_MATCH,
            checks=[], confidence=0.5, needs_human=False, explanation="x", sources=[],
        )


def test_naive_datetimes_rejected():
    from datetime import datetime

    from amber_lens.schemas import Sighting

    with pytest.raises(ValidationError):
        Sighting(model_number="M", room_tag="R", observation_id="o", seen_at=datetime(2026, 11, 24))
