"""Shared contracts for Amber Lens.

Every module (perception, records, verdict, sitepr, mcp_server, eval) talks
through these models. Changing a field here breaks other people's code, so any
PR touching this file needs two approvals.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


def utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- #
# Sources: every answer must point at where it came from.
# --------------------------------------------------------------------------- #


class BBox(BaseModel):
    """Pixel box inside a photo: (x, y) top-left, width, height."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(gt=0)
    h: int = Field(gt=0)


class SourceRef(BaseModel):
    """A pointer to the evidence behind a field, match or decision."""

    kind: Literal["photo_crop", "po_line", "submittal", "datasheet", "schedule_row", "room", "delivery", "sighting"]
    ref_id: str = Field(description="Photo ID, PO number + line, submittal ID, etc.")
    detail: str | None = Field(default=None, description="Page, row, field name or note")
    bbox: BBox | None = Field(default=None, description="Required when kind == photo_crop")

    @model_validator(mode="after")
    def _crop_needs_bbox(self) -> SourceRef:
        if self.kind == "photo_crop" and self.bbox is None:
            raise ValueError("photo_crop sources must include a bbox")
        return self


# --------------------------------------------------------------------------- #
# A. Perception
# --------------------------------------------------------------------------- #


class Observation(BaseModel):
    """One capture from the phone. No GPS, no person identity."""

    observation_id: str
    kind: Literal["nameplate", "crate_label", "delivery_ticket", "packing_slip"]
    device_id: str
    role: str = Field(description="e.g. 'site engineer', never a name")
    room_tag: str | None = Field(default=None, description="Decoded room QR tag; None if not scanned")
    photo_path: str
    captured_at: datetime = Field(default_factory=utcnow)


class ReadStatus(str, Enum):
    READ = "read"  # vision model + format rule agree, OCR does not contradict
    DISPUTED = "disputed"  # readers disagree and no rule resolves it
    UNREADABLE = "unreadable"  # nothing usable


class ReadField(BaseModel):
    """One field read from a photo, with the crop it came from."""

    name: str = Field(description="e.g. model_number, voltage, rated_current, sccr, serial, qty")
    value: str | None = Field(description="None unless status == READ")
    vision_value: str | None = None
    ocr_value: str | None = None
    format_rule_passed: bool | None = None
    status: ReadStatus
    source: SourceRef
    injection_flag: bool = Field(default=False, description="Read text looked like an instruction to an AI")

    @model_validator(mode="after")
    def _value_only_when_read(self) -> ReadField:
        if self.status != ReadStatus.READ and self.value is not None:
            raise ValueError("value must be None unless the field is READ (flag, never guess)")
        return self


class PerceptionResult(BaseModel):
    observation_id: str
    fields: list[ReadField]
    tag_read_ok: bool
    model_name: str
    latency_ms: int
    cost_usd: float


# --------------------------------------------------------------------------- #
# B. Records (Project Alpha)
# --------------------------------------------------------------------------- #


class POLine(BaseModel):
    po_number: str
    line: int
    equipment_tag: str | None = None
    model_number: str
    description: str
    qty: int = Field(ge=0)
    submittal_id: str | None = None


class Submittal(BaseModel):
    submittal_id: str
    model_number: str
    status: Literal["approved", "approved_as_noted", "revise_resubmit", "rejected", "pending"]
    datasheet_path: str | None = Field(default=None, description="Official datasheet PDF, when we found one")
    datasheet_source_url: str | None = None
    ratings: dict[str, str] = Field(description="Approved values for this model, e.g. {'voltage': '460V', 'hp': '50'}")
    allowed_suffixes: list[str] = Field(default_factory=list, description="Equivalent suffixes that pass as GO")


class ScheduleItem(BaseModel):
    """A row of the equipment schedule on the drawings."""

    equipment_tag: str
    model_number: str
    room_tag: str
    drawing_ref: str
    activity_id: str | None = None
    float_days: int | None = None


class Delivery(BaseModel):
    delivery_id: str
    po_number: str
    line: int
    qty_received: int | None = None
    status: Literal["expected", "partial", "received", "claimed"] = "expected"


class Sighting(BaseModel):
    """Minimal site memory: where an item was seen, and when."""

    model_number: str
    equipment_tag: str | None = None
    room_tag: str
    observation_id: str
    seen_at: datetime


# --------------------------------------------------------------------------- #
# C. Verdicts
# --------------------------------------------------------------------------- #


class VerdictCode(str, Enum):
    GO = "GO"
    HOLD = "HOLD"
    DEVIATES = "DEVIATES"
    SHORT = "SHORT"
    OVER = "OVER"
    CANT_MATCH = "CANT_MATCH"


class CheckResult(BaseModel):
    """One deterministic rule run inside a verdict."""

    name: str = Field(description="e.g. model_matches_po, room_matches_schedule, rating_matches_datasheet")
    passed: bool | None = Field(description="None when the rule lacked data to run")
    expected: str | None = None
    found: str | None = None
    match_type: Literal["exact", "normalised", "alias", "fuzzy", "none"] = "none"
    sources: list[SourceRef] = Field(default_factory=list)


class Verdict(BaseModel):
    verdict_id: str
    observation_id: str
    check_type: Literal["substitution", "gate", "pre_install"]
    verdict: VerdictCode
    checks: list[CheckResult]
    confidence: float = Field(ge=0.0, le=1.0)
    needs_human: bool
    explanation: str = Field(description="One line; written by the model, never decides the verdict")
    next_action: str | None = None
    impact: str | None = Field(default=None, description="e.g. 'feeds L2 switchboard activity; 6 days float'")
    sources: list[SourceRef]

    @model_validator(mode="after")
    def _go_needs_every_check_sourced(self) -> Verdict:
        if self.verdict == VerdictCode.GO:
            if not self.checks:
                raise ValueError("GO requires at least one check")
            for c in self.checks:
                if c.passed is not True or not c.sources:
                    raise ValueError(f"GO requires every check passed and sourced; failed on '{c.name}'")
        return self


# --------------------------------------------------------------------------- #
# C. Site PRs and the ledger
# --------------------------------------------------------------------------- #


class SitePRStatus(str, Enum):
    DRAFT = "draft"
    WITHDRAWN = "withdrawn"  # self-check found the fix would be wrong
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    WRITTEN = "written"
    VERIFIED = "verified"
    REOPENED = "reopened"  # read-back failed, or the issue recurred after approval


# Allowed status transitions. Anything else is a bug.
SITEPR_TRANSITIONS: dict[SitePRStatus, set[SitePRStatus]] = {
    SitePRStatus.DRAFT: {SitePRStatus.WITHDRAWN, SitePRStatus.PENDING_REVIEW},
    SitePRStatus.PENDING_REVIEW: {SitePRStatus.APPROVED, SitePRStatus.REJECTED},
    SitePRStatus.APPROVED: {SitePRStatus.WRITTEN},
    SitePRStatus.WRITTEN: {SitePRStatus.VERIFIED, SitePRStatus.REOPENED},
    SitePRStatus.VERIFIED: {SitePRStatus.REOPENED},
    SitePRStatus.REOPENED: {SitePRStatus.PENDING_REVIEW, SitePRStatus.WITHDRAWN},
    SitePRStatus.WITHDRAWN: set(),
    SitePRStatus.REJECTED: set(),
}


def can_transition(src: SitePRStatus, dst: SitePRStatus) -> bool:
    return dst in SITEPR_TRANSITIONS[src]


class RecordChange(BaseModel):
    """A proposed change to the procurement records."""

    record_kind: Literal["po_line", "delivery", "submittal", "claim"]
    record_id: str
    field: str
    old_value: str | None
    new_value: str


class SitePR(BaseModel):
    site_pr_id: str
    verdict_id: str
    status: SitePRStatus = SitePRStatus.DRAFT
    finding: str
    changes: list[RecordChange]
    evidence: list[SourceRef]
    self_check_note: str | None = None
    impact: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    idempotency_key: str = Field(description="e.g. 'sitepr-0042:claim:v1'; a write with a seen key is skipped")
    evidence_hash: str | None = Field(default=None, description="sha256 of the evidence pack, frozen at approval")
    recurrence_count: int = Field(default=0, ge=0, description="Times this issue reappeared after approval")


class LedgerEvent(BaseModel):
    """Append-only. The ledger is the source of truth for every Site PR."""

    event_id: str
    site_pr_id: str
    type: Literal["drafted", "self_checked", "withdrawn", "submitted", "approved", "rejected", "written", "verified", "reopened"]
    actor: str = Field(description="component name or reviewer role, never a person's name")
    at: datetime = Field(default_factory=utcnow)
    payload: dict = Field(default_factory=dict)
    idempotency_key: str | None = None
