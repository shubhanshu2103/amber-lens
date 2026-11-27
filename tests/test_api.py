import pytest
from fastapi.testclient import TestClient

from amber_lens.api.app import create_app
from amber_lens.schemas import BBox, RecordChange, SitePR, SourceRef
from amber_lens.sitepr import Ledger, MockRecordStore, SitePRService

EVID = [SourceRef(kind="photo_crop", ref_id="obs-1", bbox=BBox(x=1, y=1, w=5, h=5))]


def make_pr(pid):
    return SitePR(
        site_pr_id=pid,
        verdict_id="v-1",
        finding="Delivered qty 10 vs PO 12",
        changes=[
            RecordChange(record_kind="delivery", record_id="D-7", field="qty_received", old_value="12", new_value="10")
        ],
        evidence=EVID,
        confidence=0.9,
        idempotency_key=f"{pid}:claim:v1",
    )


@pytest.fixture
def client(tmp_path):
    store = MockRecordStore(tmp_path / "store.db")
    svc = SitePRService(Ledger(tmp_path / "ledger.db"), store)
    for pid in ("sitepr-1", "sitepr-2"):
        svc.draft(make_pr(pid))
        svc.submit(pid)
    return TestClient(create_app(svc))


def test_list_and_view(client):
    rows = client.get("/site-prs").json()
    assert {r["site_pr_id"] for r in rows} == {"sitepr-1", "sitepr-2"}
    assert client.get("/site-prs", params={"status": "approved"}).json() == []
    one = client.get("/site-prs/sitepr-1").json()
    assert one["status"] == "pending_review" and one["finding"].startswith("Delivered")


def test_unknown_is_404(client):
    assert client.get("/site-prs/nope").status_code == 404
    assert client.post("/site-prs/nope/approve", json={"reviewer_role": "project manager"}).status_code == 404


def test_approve_and_reject(client):
    ok = client.post("/site-prs/sitepr-1/approve", json={"reviewer_role": "project manager", "note": "ok"})
    assert ok.status_code == 200 and ok.json()["status"] == "approved" and ok.json()["evidence_hash"]
    no = client.post("/site-prs/sitepr-2/reject", json={"reviewer_role": "project manager", "note": "wrong qty"})
    assert no.status_code == 200 and no.json()["status"] == "rejected"


def test_only_a_reviewer_role_may_approve(client):
    r = client.post("/site-prs/sitepr-1/approve", json={"reviewer_role": "storekeeper"})
    assert r.status_code == 409
    assert client.get("/site-prs/sitepr-1").json()["status"] == "pending_review"
