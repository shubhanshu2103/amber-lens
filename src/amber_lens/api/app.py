"""HTTP API for the review UI. A thin layer over SitePRService: no Site PR logic lives here."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from amber_lens.schemas import SitePR, SitePRStatus
from amber_lens.sitepr import SitePRService, TransitionError


class Review(BaseModel):
    reviewer_role: str
    note: str = ""


def create_app(service: SitePRService) -> FastAPI:
    app = FastAPI(title="Amber Lens review API")

    def _known(site_pr_id: str) -> None:
        if not service.ledger.events(site_pr_id):
            raise HTTPException(status_code=404, detail=f"unknown Site PR {site_pr_id!r}")

    @app.get("/site-prs", response_model=list[SitePR])
    def list_site_prs(status: SitePRStatus | None = None):
        return service.list(status)

    @app.get("/site-prs/{site_pr_id}", response_model=SitePR)
    def get_site_pr(site_pr_id: str):
        _known(site_pr_id)
        return service.get(site_pr_id)

    @app.post("/site-prs/{site_pr_id}/approve", response_model=SitePR)
    def approve_site_pr(site_pr_id: str, body: Review):
        _known(site_pr_id)
        try:
            return service.approve(site_pr_id, body.reviewer_role, body.note)
        except TransitionError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e

    @app.post("/site-prs/{site_pr_id}/reject", response_model=SitePR)
    def reject_site_pr(site_pr_id: str, body: Review):
        _known(site_pr_id)
        try:
            return service.reject(site_pr_id, body.reviewer_role, body.note)
        except TransitionError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e

    return app
