"""MCP server for Amber: six tools over the Amber Lens checks and Site PRs.

Run:  python -m amber_lens.mcp_server.server        (stdio, for Claude Desktop or the MCP inspector)

Every tool returns JSON with `sources` and `confidence`. A tool never raises to the client: a problem comes back as
{"error": ..., "sources": [], "confidence": 0.0}.

Settings (environment variables, all optional):
  AMBER_RECORDS_DIR   folder with the record CSVs        (default: data/records)
  AMBER_STATE_DIR     folder for the ledger and mock store (default: .amber_state)
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

try:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:  # mcp 2.x renamed it
    from mcp.server.mcpserver import MCPServer as FastMCP

from amber_lens.perception.documents import read_observation
from amber_lens.perception.reader import PerceptionError
from amber_lens.records.store import RecordStore
from amber_lens.schemas import Observation, PerceptionResult, SitePR, SitePRStatus, Verdict
from amber_lens.sitepr import Ledger, MockRecordStore, SitePRService, TransitionError
from amber_lens.verdict.gate import check_gate, draft_gate_site_pr
from amber_lens.verdict.preinstall import check_pre_install
from amber_lens.verdict.substitution import check_substitution as run_substitution

DEVICE_ID = "mcp-client"
DEFAULT_ROLE = "site engineer"


class Context:
    """Records, Site PR service and what the server has seen so far (for get_evidence)."""

    def __init__(self, records: RecordStore, service: SitePRService):
        self.records = records
        self.service = service
        self.verdicts: dict[str, Verdict] = {}
        self.perceptions: dict[str, PerceptionResult] = {}

    @classmethod
    def from_env(cls) -> Context:
        records_dir = Path(os.environ.get("AMBER_RECORDS_DIR", "data/records"))
        state = Path(os.environ.get("AMBER_STATE_DIR", ".amber_state"))
        state.mkdir(parents=True, exist_ok=True)
        service = SitePRService(Ledger(state / "ledger.db"), MockRecordStore(state / "records.db"))
        return cls(RecordStore.from_csv_dir(records_dir), service)


def _dump(model: Any) -> Any:
    return model.model_dump(mode="json")


def _error(message: str) -> dict:
    return {"error": message, "sources": [], "confidence": 0.0}


def _observation(kind: str, photo_path: str, room_tag: str | None = None) -> Observation:
    return Observation(
        observation_id=f"obs-{uuid.uuid4().hex[:8]}",
        kind=kind,
        device_id=DEVICE_ID,
        role=DEFAULT_ROLE,
        room_tag=room_tag,
        photo_path=photo_path,
    )


def _verdict_payload(ctx: Context, verdict: Verdict, site_pr: SitePR | None = None) -> dict:
    ctx.verdicts[verdict.verdict_id] = verdict
    out = {
        "verdict": _dump(verdict),
        "sources": [_dump(s) for s in verdict.sources],
        "confidence": verdict.confidence,
    }
    if site_pr is not None:
        out["site_pr"] = _dump(site_pr)
    return out


def _read(ctx: Context, obs: Observation) -> PerceptionResult:
    perception = read_observation(obs)
    ctx.perceptions[obs.observation_id] = perception
    return perception


def _pr_payload(pr: SitePR) -> dict:
    return {"site_pr": _dump(pr), "sources": [_dump(s) for s in pr.evidence], "confidence": pr.confidence}


def build_server(ctx: Context | None = None) -> FastMCP:
    mcp = FastMCP("amber-lens")
    state: dict[str, Context] = {}

    def get_ctx() -> Context:
        if "ctx" not in state:
            state["ctx"] = ctx or Context.from_env()
        return state["ctx"]

    @mcp.tool()
    def check_item(photo_path: str, room_tag: str | None = None) -> dict:
        """Pre-install check of an equipment nameplate photo against the schedule, PO and submittal.

        Returns a Verdict (GO / HOLD / CANT_MATCH) with sources and confidence."""
        c = get_ctx()
        try:
            obs = _observation("nameplate", photo_path, room_tag)
            verdict = check_pre_install(obs, _read(c, obs), c.records)
        except (PerceptionError, ValueError, OSError) as e:
            return _error(str(e))
        return _verdict_payload(c, verdict)

    @mcp.tool()
    def check_substitution(photo_path: str) -> dict:
        """Compare a nameplate photo with the approved submittal to catch a substituted model or rating.

        Returns a Verdict with sources and confidence."""
        c = get_ctx()
        try:
            obs = _observation("nameplate", photo_path)
            verdict = run_substitution(obs, _read(c, obs), c.records)
        except (PerceptionError, ValueError, OSError) as e:
            return _error(str(e))
        return _verdict_payload(c, verdict)

    @mcp.tool()
    def check_delivery(ticket_photo_path: str, po_number: str) -> dict:
        """Check a delivery ticket photo against the PO: SHORT, OVER or GO for each PO line on the ticket.

        A SHORT or OVER verdict also drafts a Site PR. Returns one result per line, each with sources and confidence."""
        c = get_ctx()
        try:
            obs = _observation("delivery_ticket", ticket_photo_path)
            perception = _read(c, obs)
            verdicts = check_gate(obs, perception, c.records)
        except (PerceptionError, ValueError, OSError) as e:
            return _error(str(e))
        read_po = next((f.value for f in perception.fields if f.name == "po_number" and f.value), None)
        mismatch = read_po is not None and read_po.strip().upper() != po_number.strip().upper()
        results = []
        for v in verdicts:
            if mismatch:
                v = v.model_copy(update={"needs_human": True, "flags": [*v.flags, "po_number_mismatch"]})
            pr = None if mismatch else draft_gate_site_pr(v, f"sitepr-{v.verdict_id}")
            if pr is not None:
                pr = c.service.draft(pr)
            results.append(_verdict_payload(c, v, pr))
        confidence = min((r["confidence"] for r in results), default=0.0)
        out = {
            "results": results,
            "sources": [s for r in results for s in r["sources"]],
            "confidence": confidence,
        }
        if mismatch:
            out["warning"] = f"ticket reads PO {read_po!r} but {po_number!r} was given; sent to a person"
        return out

    @mcp.tool()
    def list_site_prs(status: str | None = None) -> dict:
        """List Site PRs, optionally filtered by status (for example 'submitted' or 'approved')."""
        c = get_ctx()
        try:
            wanted = SitePRStatus(status) if status else None
        except ValueError:
            return _error(f"unknown status {status!r}; use one of {[s.value for s in SitePRStatus]}")
        prs = c.service.list(wanted)
        return {
            "site_prs": [_dump(p) for p in prs],
            "sources": [_dump(s) for p in prs for s in p.evidence],
            "confidence": min((p.confidence for p in prs), default=1.0),
        }

    @mcp.tool()
    def approve_site_pr(site_pr_id: str, reviewer_role: str, decision: str, note: str = "") -> dict:
        """Approve or reject a Site PR. decision is 'approve' or 'reject'. Only a person's role may approve."""
        c = get_ctx()
        if decision not in ("approve", "reject"):
            return _error("decision must be 'approve' or 'reject'")
        if not c.service.ledger.events(site_pr_id):
            return _error(f"unknown Site PR {site_pr_id!r}")
        try:
            pr = (c.service.approve if decision == "approve" else c.service.reject)(site_pr_id, reviewer_role, note)
        except TransitionError as e:
            return _error(str(e))
        return _pr_payload(pr)

    @mcp.tool()
    def get_evidence(id: str) -> dict:
        """Evidence pack for a verdict ID or a Site PR ID: every source behind it, with the fields read from the photo."""
        c = get_ctx()
        verdict = c.verdicts.get(id)
        if verdict is not None:
            perception = c.perceptions.get(verdict.observation_id)
            return {
                "kind": "verdict",
                "verdict": _dump(verdict),
                "checks": [_dump(k) for k in verdict.checks],
                "fields_read": [_dump(f) for f in perception.fields] if perception else [],
                "sources": [_dump(s) for s in verdict.sources],
                "confidence": verdict.confidence,
            }
        if c.service.ledger.events(id):
            pr = c.service.get(id)
            return {
                "kind": "site_pr",
                **_pr_payload(pr),
                "ledger": [_dump(e) for e in c.service.ledger.events(id)],
            }
        return _error(f"no verdict or Site PR with id {id!r}")

    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
