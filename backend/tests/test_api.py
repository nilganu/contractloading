"""API smoke tests using FastAPI TestClient."""
from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import Job, SessionLocal, init_db
from app.main import app


def _wait_for(client: TestClient, job_id: str, *, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        r = client.get(f"/api/contracts/jobs/{job_id}")
        last = r.json()
        if last.get("status") in ("ready_for_review", "completed", "failed"):
            return last
        time.sleep(0.2)
    raise AssertionError(f"Job did not finish in time. Last status: {last}")


def test_upload_and_review_flow(sample_xlsx: Path) -> None:
    init_db()
    client = TestClient(app)
    with open(sample_xlsx, "rb") as fh:
        resp = client.post(
            "/api/contracts/upload",
            files={"file": (sample_xlsx.name, fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={
                "supplierDefault": "TestCo",
                "countryDefault": "EG",
                "currencyDefault": "EUR",
                "childColumnMode": "dynamic_review",
                "extractionMode": "text_only",
            },
        )
    assert resp.status_code == 200, resp.text
    job = resp.json()
    job_id = job["id"]
    final = _wait_for(client, job_id)
    assert final["status"] == "ready_for_review", final

    r = client.get(f"/api/contracts/jobs/{job_id}/result")
    assert r.status_code == 200
    data = r.json()
    assert "hotelRows" in data["result"]
    assert "dynamicColumns" in data["result"]
    assert len(data["result"]["workbookSummary"]["hotelSheets"]) >= 3


def test_template_endpoint() -> None:
    init_db()
    client = TestClient(app)
    r = client.get("/api/contracts/template")
    assert r.status_code == 200
    body = r.json()
    assert "Hotel Name" in body["fixedBaseHeaders"]
    assert "Country Code " in body["fixedBaseHeaders"]
    assert "SUPP-AI-CHILD" in body["fixedSupplementHeaders"]


def test_export_blocked_by_errors(sample_xlsx: Path) -> None:
    init_db()
    client = TestClient(app)
    with open(sample_xlsx, "rb") as fh:
        resp = client.post(
            "/api/contracts/upload",
            files={"file": (sample_xlsx.name, fh, "application/octet-stream")},
            data={
                "supplierDefault": "TestCo",
                "currencyDefault": "EUR",
                "childColumnMode": "dynamic_export",
                "extractionMode": "text_only",
            },
        )
    assert resp.status_code == 200
    job_id = resp.json()["id"]
    _wait_for(client, job_id)

    r = client.get(f"/api/contracts/jobs/{job_id}/export.xlsx")
    # Room Name missing in every row -> blocking errors -> 422
    assert r.status_code == 422


def test_patch_result_clears_errors_and_allows_export(sample_xlsx: Path, tmp_path: Path) -> None:
    init_db()
    client = TestClient(app)
    with open(sample_xlsx, "rb") as fh:
        resp = client.post(
            "/api/contracts/upload",
            files={"file": (sample_xlsx.name, fh, "application/octet-stream")},
            data={
                "supplierDefault": "TestCo",
                "currencyDefault": "EUR",
                "childColumnMode": "dynamic_export",
                "extractionMode": "text_only",
            },
        )
    job_id = resp.json()["id"]
    _wait_for(client, job_id)
    data = client.get(f"/api/contracts/jobs/{job_id}/result").json()["result"]

    # Fill missing Room Name on every row.
    for row in data["hotelRows"]:
        row["Room Name"] = "Standard Double"

    patch = client.patch(
        f"/api/contracts/jobs/{job_id}/result", json={"result": data}
    )
    assert patch.status_code == 200
    blocking = [i for i in patch.json()["result"]["validationIssues"] if i["severity"] == "error"]
    assert blocking == [], blocking

    export = client.get(f"/api/contracts/jobs/{job_id}/export.xlsx")
    assert export.status_code == 200
    out = tmp_path / "out.xlsx"
    out.write_bytes(export.content)
    assert out.stat().st_size > 0
