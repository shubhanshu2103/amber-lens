"""Gate check: does what arrived match what was ordered?

One verdict per PO line on the document. Rows that point at the same PO line (a split line) are checked as one, with their
quantities added. A crate label is a single row.

    po_line_found       the ticket's PO number and line exist in the records
    model_matches_po    every row's model is the PO line's model (spacing, dashes and case ignored)
    qty_matches_po      delivered quantity equals what is still outstanding: ordered minus already received, leaving out
                        the ticket being checked so a rescan gives the same answer

Outcome: anything we could not read, find or trust -> CANT_MATCH. That includes an unread quantity (never 0), a quantity of
0, a different model, and a PO line that already shows more received than ordered. Otherwise fewer than outstanding ->
SHORT, more -> OVER, equal -> GO. SHORT and OVER can be turned into a draft Site PR with `draft_gate_site_pr`.
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

    def received_so_far(self, po_number: str, line: int, exclude_ticket_id: str | None = None) -> int:
        """Quantity already received on this PO line, leaving out receipts recorded for `exclude_ticket_id`.

        Receipts are recorded after the gate runs, so for a crate label (no ticket id) the caller passes None.
        """
        ...


def _norm(s: str) -> str:
    return re.sub(r"[\s\-_]", "", s).upper()


def _int(s: str | None) -> int | None:
    return int(s.strip()) if s and re.fullmatch(r"[0-9]+", s.strip()) else None


def _unique(sources: list[SourceRef]) -> list[SourceRef]:
    seen, out = set(), []
    for s in sources:
        key = s.model_dump_json()
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out


def _crop(f: ReadField | None) -> list[SourceRef]:
    return [f.source] if f and f.source else []


def _read(fields: dict[str, ReadField], name: str) -> ReadField | None:
    f = fields.get(name)
    return f if f and f.status == ReadStatus.READ and f.value else None


def _rows(perception: PerceptionResult) -> list[tuple[int, dict[str, ReadField]]]:
    """Fields per ticket row; a crate label has no `line[n].` prefix and counts as row 1."""
    top = {f.name: f for f in perception.fields}
    grouped: dict[int, dict[str, ReadField]] = {}
    for f in perception.fields:
        m = LINE_FIELD.match(f.name)
        if m:
            grouped.setdefault(int(m.group(1)), {})[m.group(2)] = f
    if not grouped:
        grouped = {1: {k: top[k] for k in ("model_number", "qty", "po_line") if k in top}}
    shared = {k: top[k] for k in ("po_number",) if k in top}
    return [(n, {**shared, **g}) for n, g in sorted(grouped.items())]


def _group_key(n: int, fields: dict[str, ReadField]) -> tuple:
    po_no, line = _read(fields, "po_number"), _int(getattr(_read(fields, "po_line"), "value", None))
    return (po_no.value, line) if po_no and line is not None else ("row", n)


def _model_check(rows: list[dict[str, ReadField]], po: POLine, po_src: SourceRef) -> CheckResult:
    models = [_read(r, "model_number") for r in rows]
    if any(m is None for m in models):
        return CheckResult(name="model_matches_po", passed=None, expected=po.model_number)
    found = ", ".join(sorted({m.value for m in models}))
    kinds = {"exact" if m.value == po.model_number else "normalised" if _norm(m.value) == _norm(po.model_number) else None
             for m in models}
    if None in kinds:
        return CheckResult(name="model_matches_po", passed=None, expected=po.model_number, found=found)
    return CheckResult(name="model_matches_po", passed=True, expected=po.model_number, found=found,
                       match_type="normalised" if "normalised" in kinds else "exact",
                       sources=[*[s for m in models for s in _crop(m)], po_src])


def _qty_check(rows: list[dict[str, ReadField]], po: POLine, po_src: SourceRef, outstanding: int) -> CheckResult:
    qtys = [_read(r, "qty") for r in rows]
    nums = [_int(q.value) if q else None for q in qtys]
    if any(n is None for n in nums) or any(n == 0 for n in nums) or outstanding < 0:
        # unread, zero, or a line that already shows more received than ordered: a person decides
        return CheckResult(name="qty_matches_po", passed=None, expected=str(outstanding))
    total = sum(nums)
    return CheckResult(name="qty_matches_po", passed=total == outstanding, expected=str(outstanding), found=str(total),
                       match_type="exact", sources=[*[s for q in qtys for s in _crop(q)], po_src])


def _check_group(
    rows: list[dict[str, ReadField]], ticket_id: str | None, records: GateRecords
) -> list[CheckResult]:
    first = rows[0]
    po_no, line_no = _read(first, "po_number"), _int(getattr(_read(first, "po_line"), "value", None))
    po = records.po_line(po_no.value, line_no) if po_no and line_no is not None else None
    if po is None:
        shown = f"{po_no.value}:{line_no}" if po_no and line_no is not None else None
        return [CheckResult(name="po_line_found", passed=None, found=shown),
                *[CheckResult(name=n, passed=None) for n in CHECK_NAMES[1:]]]
    po_src = SourceRef(kind="po_line", ref_id=f"{po.po_number}:{po.line}")
    outstanding = po.qty - records.received_so_far(po.po_number, po.line, exclude_ticket_id=ticket_id)
    found = CheckResult(name="po_line_found", passed=True, expected=po_src.ref_id, found=po_src.ref_id,
                        match_type="exact", sources=[po_src])
    return [found, _model_check(rows, po, po_src), _qty_check(rows, po, po_src, outstanding)]


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
        diff = abs(int(qty.found) - int(qty.expected))
        return f"Delivered {qty.found}, outstanding {qty.expected} ({word} by {diff}).", "Review the drafted Site PR."
    if code == VerdictCode.CANT_MATCH:
        names = ", ".join(c.name.replace("_", " ") for c in checks if c.passed is None)
        return f"Not enough evidence to compare with the PO ({names}).", "Retake the photo or send to a person."
    return f"Delivered quantity {qty.found} matches the PO.", "Receive the delivery."


def check_gate(observation: Observation, perception: PerceptionResult, records: GateRecords) -> list[Verdict]:
    flagged = [f for f in perception.fields if f.injection_flag]
    ticket = next((f for f in perception.fields if f.name == "delivery_ticket_id" and f.status == ReadStatus.READ), None)
    ticket_id = ticket.value if ticket else None
    groups: dict[tuple, list[tuple[int, dict[str, ReadField]]]] = {}
    for n, fields in _rows(perception):
        groups.setdefault(_group_key(n, fields), []).append((n, fields))

    out = []
    for members in groups.values():
        rows = [f for _, f in members]
        checks = _check_group(rows, ticket_id, records)
        code = _decide(checks)
        used = [f for r in rows for f in r.values() if f.status == ReadStatus.READ]
        confidence = compute_confidence(checks, used, injection=bool(flagged))
        explanation, next_action = _explain(code, checks)
        out.append(Verdict(
            verdict_id=f"v-{observation.observation_id}-gate-{members[0][0]}",
            observation_id=observation.observation_id,
            check_type="gate",
            verdict=code,
            checks=checks,
            confidence=confidence,
            needs_human=needs_human(confidence, used + flagged) or code == VerdictCode.CANT_MATCH,
            explanation=explanation,
            next_action=next_action,
            sources=_unique([s for c in checks for s in c.sources]),
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
        evidence=_unique(verdict.sources),
        confidence=verdict.confidence,
        idempotency_key=f"{site_pr_id}:claim:v1",
    )
