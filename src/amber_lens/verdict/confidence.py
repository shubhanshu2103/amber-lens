"""Confidence from signals. The model's own number is never used.

    confidence = completeness * (0.4 * agreement + 0.4 * match + 0.2 * tag)

completeness  share of checks that had data to run (passed is not None)
agreement     share of the fields behind the verdict that were READ (see `field_agreement`). Pass only the fields the
              checks actually use, since every field passed in counts toward the average
match         average weight of how each check matched: exact 1.0, normalised 0.95, alias 0.85, fuzzy 0.6, none 0.5
tag           1.0 if the room tag was read cleanly (or no tag is involved), else 0.6

An injection flag on any field of the document caps the result at 0.5. Below CONFIDENCE_REVIEW_THRESHOLD the verdict goes to a human.
"""

from __future__ import annotations

from collections.abc import Sequence

from amber_lens.schemas import CONFIDENCE_REVIEW_THRESHOLD, CheckResult, ReadField, ReadStatus

__all__ = ["CONFIDENCE_REVIEW_THRESHOLD", "MATCH_WEIGHT", "compute_confidence", "field_agreement", "needs_human"]

MATCH_WEIGHT = {"exact": 1.0, "normalised": 0.95, "alias": 0.85, "fuzzy": 0.6, "none": 0.5}
INJECTION_CAP = 0.5
BAD_TAG = 0.6


def field_agreement(fields: Sequence[ReadField]) -> float:
    """READ = 1.0, disputed/unreadable = 0.

    Perception already checked the format rule and that OCR found the same characters before it says READ, and the OCR
    span legitimately differs from the vision value in units and spacing, so the raw strings are not compared here.
    """
    if not fields:
        return 0.0
    return sum(1.0 for f in fields if f.status == ReadStatus.READ) / len(fields)


def compute_confidence(
    checks: Sequence[CheckResult],
    fields: Sequence[ReadField],
    tag_read_ok: bool | None = None,
    injection: bool = False,
) -> float:
    """tag_read_ok=None means the check does not use a room tag (substitution, gate).

    injection=True means some field on the document was flagged, including a free_text_n line the check never reads.
    """
    if not checks:
        return 0.0
    ran = [c for c in checks if c.passed is not None]
    if not ran:
        return 0.0
    completeness = len(ran) / len(checks)
    match = sum(MATCH_WEIGHT[c.match_type] for c in ran) / len(ran)
    tag = 1.0 if tag_read_ok in (None, True) else BAD_TAG
    conf = completeness * (0.4 * field_agreement(fields) + 0.4 * match + 0.2 * tag)
    if injection or any(f.injection_flag for f in fields):
        conf = min(conf, INJECTION_CAP)
    return round(max(0.0, min(1.0, conf)), 3)


def needs_human(confidence: float, fields: Sequence[ReadField] = ()) -> bool:
    return confidence < CONFIDENCE_REVIEW_THRESHOLD or any(f.injection_flag for f in fields)
