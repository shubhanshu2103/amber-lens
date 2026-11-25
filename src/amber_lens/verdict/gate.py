"""Gate check: does what arrived match what was ordered?

One verdict per ticket line (a crate label is a single line). Quantities are compared per PO line.

    po_line_found       the ticket's PO number and line exist in the records
    model_matches_po    the model on the ticket is the PO line's model (spacing, dashes and case ignored)
    qty_matches_po      delivered quantity equals ordered quantity

Outcome: anything we could not read or find -> CANT_MATCH (an unread quantity is never 0, and a different model means
we cannot trust the quantity comparison). Otherwise fewer than ordered -> SHORT, more -> OVER, equal -> GO.
SHORT and OVER can be turned into a draft Site PR with `draft_gate_site_pr`.
"""

from __future__ import annotations

import re
from typing import Protocol

from amber_lens.schemas import (
    CheckResult,
    Observation,
    PerceptionResult,
    POLine,
    ReadField,
    ReadStatus,
    RecordChange,
    SitePR,
    SourceRef,
    Verdict,
    VerdictCode,
)
from amber_lens.verdict.confidence import compute_confidence, needs_human

CHECK_NAMES = ("po_line_found", "model_matches_po", "qty_matches_po")
LINE_FIELD = re.compile(r"^line\[(\d+)\]\.(.+)$")


class GateRecords(Protocol):
    def po_line(self, po_number: str, line: int) -> POLine | None: ...


def _norm(s: str) -> str:
    return re.sub(r"[\s\-_]", "", s).upper()


def _int(s: str | None) -> int | None:
    return int(s) if s and s.strip().isdigit() else None


def _crop(f: ReadField | None) -> list[SourceRef]:
    return [f.source] if f and f.source else []


def _read(fields: dict[str, ReadField], name: str) -> ReadField | None:
    f = fields.get(name)
    return f if f and f.status == ReadStatus.READ and f.value else None


def _line_groups(perception: PerceptionResult) -> list[tuple[int, dict[str, ReadField]]]:
    """Group fields by ticket line; a crate label has no `line[n].` prefix and counts as line 1."""
    top = {f.name: f for f in perception.fields}
    grouped: dict[int, dict[str, ReadField]] = {}
    for f in perception.fields:
        m = LINE_FIELD.match(f.name)
        if m:
            grouped.setdefault(int(m.group(1)), {})[m.group(2)] = f
    if not grouped:
        grouped = {1: {k: top[k] for k in ("model_number", "qty", "po_line") if k in top}}
    return [(n, {**{k: top[k] for k in ("po_number",) if k in top}, **g}) for n, g in sorted(grouped.items())]


def _check_line(fields: dict[str, ReadField], records: GateRecords) -> tuple[list[CheckResult], list[ReadField], POLine | None]:
    used = [f for f in fields.values() if f.status == ReadStatus.READ]
    po_no, line_no = _read(fields, "po_number"), _int(getattr(_read(fields, "po_line"), "value", None))
    po = records.po_line(po_no.value, line_no) if po_no and line_no is not None else None
    if po is None:
        found = CheckResult(name="po_line_found", passed=None, found=f"{po_no.value}:{line_no}" if po_no and line_no else None)
        return [found, *[CheckResult(name=n, passed=None) for n in CHECK_NAMES[1:]]], used, None

    po_src = SourceRef(kind="po_line", ref_id=f"{po.po_number}:{po.line}")
    model, qty = _read(fields, "model_number"), _read(fields, "qty")
    qty_n = _int(qty.value) if qty else None

    if model is None:
        model_check = CheckResult(name="model_matches_po", passed=None, expected=po.model_number)
    elif model.value == po.model_number:
        model_check = CheckResult(name="model_matches_po", passed=True, expected=po.model_number, found=model.value,
                                  match_type="exact", sources=[*_crop(model), po_src])
    elif _norm(model.value) == _norm(po.model_number):
        model_check = CheckResult(name="model_matches_po", passed=True, expected=po.model_number, found=model.value,
                                  match_type="normalised", sources=[*_crop(model), po_src])
    else:
        model_check = CheckResult(name="model_matches_po", passed=None, expected=po.model_number, found=model.value)

    if qty_n is None:
        qty_check = CheckResult(name="qty_matches_po", passed=None, expected=str(po.qty))
    else:
        qty_check = CheckResult(name="qty_matches_po", passed=qty_n == po.qty, expected=str(po.qty), found=str(qty_n),
                                match_type="exact", sources=[*_crop(qty), po_src])
    found = CheckResult(name="po_line_found", passed=True, expected=f"{po.po_number}:{po.line}",
                        found=f"{po.po_number}:{po.line}", match_type="exact", sources=[po_src])
    return [found, model_check, qty_check], used, po


def _decide(checks: list[CheckResult]) -> VerdictCode:
    if any(c.passed is None for c in checks):
        return VerdictCode.CANT_MATCH
    qty = next(c for c in checks if c.name == "qty_matches_po")
    if qty.passed:
        return VerdictCode.GO
    return VerdictCode.SHORT if int(qty.found) < int(qty.expected) else VerdictCode.OVER


def _explain(code: VerdictCode, checks: list[CheckResult]) -> tuple[str, str]:
    qty = next(c for c in checks if c.name == "qty_matches_po")
    if code in (VerdictCode.SHORT, VerdictCode.OVER):
        word = "short" if code == VerdictCode.SHORT else "over"
        return f"Delivered {qty.found}, ordered {qty.expected} ({word} by {abs(int(qty.found) - int(qty.expected))}).", \
            "Review the drafted Site PR."
    if code == VerdictCode.CANT_MATCH:
        names = ", ".join(c.name.replace("_", " ") for c in checks if c.passed is None)
        return f"Not enough evidence to compare with the PO ({names}).", "Retake the photo or send to a person."
    return f"Delivered quantity {qty.found} matches the PO.", "Receive the delivery."


def check_gate(observation: Observation, perception: PerceptionResult, records: GateRecords) -> list[Verdict]:
    flagged = [f for f in perception.fields if f.injection_flag]
    out = []
    for n, fields in _line_groups(perception):
        checks, used, _ = _check_line(fields, records)
        code = _decide(checks)
        confidence = compute_confidence(checks, used)
        explanation, next_action = _explain(code, checks)
        out.append(Verdict(
            verdict_id=f"v-{observation.observation_id}-gate-{n}",
            observation_id=observation.observation_id,
            check_type="gate",
            verdict=code,
            checks=checks,
            confidence=confidence,
            needs_human=needs_human(confidence, used + flagged) or code == VerdictCode.CANT_MATCH,
            explanation=explanation,
            next_action=next_action,
            sources=[s for c in checks for s in c.sources],
            flags=["injection_flag"] if flagged else [],
            latency_ms=perception.latency_ms,
            cost_usd=perception.cost_usd,
        ))
    return out


def draft_gate_site_pr(verdict: Verdict, site_pr_id: str) -> SitePR | None:
    """A drafted shortage claim or over-delivery note for a SHORT / OVER verdict; nothing for anything else."""
    if verdict.verdict not in (VerdictCode.SHORT, VerdictCode.OVER):
        return None
    qty = next(c for c in verdict.checks if c.name == "qty_matches_po")
    po_ref = next(s.ref_id for s in verdict.sources if s.kind == "po_line")
    diff = abs(int(qty.found) - int(qty.expected))
    short = verdict.verdict == VerdictCode.SHORT
    return SitePR(
        site_pr_id=site_pr_id,
        verdict_id=verdict.verdict_id,
        finding=f"{verdict.explanation[:-1]} on PO line {po_ref}.",
        changes=[RecordChange(record_kind="claim", record_id=po_ref, field="short_qty" if short else "over_qty",
                              old_value=None, new_value=str(diff))],
        evidence=verdict.sources,
        confidence=verdict.confidence,
        idempotency_key=f"{site_pr_id}:claim:v1",
    )
