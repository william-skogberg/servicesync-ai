"""Tests use separate temp DB files and never call the real OpenAI API."""
import httpx
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from servicesync.ai_service import AnalysisOutcome, demo_analysis
from servicesync.inquiry_api import app as inquiry_app
from servicesync.mock_crm import app as crm_app


EXAMPLE = {
    "customer_name": "Demo Customer",
    "service_type": "move_out_cleaning",
    "postal_code": "00100",
    "message": "I need move-out cleaning next Friday for a 65 m2 apartment.",
}


def test_failed_transfer_can_be_retried(monkeypatch, tmp_path):
    monkeypatch.setenv("INQUIRY_DB", str(tmp_path / "inquiries.db"))
    monkeypatch.setenv("AI_MODE", "demo")
    with TestClient(inquiry_app) as client:
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                   side_effect=httpx.ConnectError("CRM offline")):
            result = client.post("/inquiries", json=EXAMPLE)
        assert result.status_code == 201
        record = result.json()
        assert record["status"] == "failed"
        assert record["delivery_attempts"] == 1
        assert record["ai_analysis"]["category"] == "move_out_cleaning"
        assert record["ai_analysis"]["area_m2"] == 65
        assert record["analysis_status"] == "demo"

        response = httpx.Response(201, request=httpx.Request("POST", "http://example.test"))
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=response):
            retry = client.post(f"/inquiries/{record['id']}/retry")
        assert retry.json()["status"] == "synced"
        assert retry.json()["delivery_attempts"] == 2
        assert client.get("/report").json()["status_counts"] == {"synced": 1}


def test_invalid_postal_code_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("INQUIRY_DB", str(tmp_path / "inquiries.db"))
    with TestClient(inquiry_app) as client:
        response = client.post("/inquiries", json={**EXAMPLE, "postal_code": "abc"})
        assert response.status_code == 422
        assert client.get("/inquiries").json() == []


def test_crm_deduplicates_repeated_deliveries(monkeypatch, tmp_path):
    monkeypatch.setenv("CRM_DB", str(tmp_path / "crm.db"))
    with TestClient(crm_app) as client:
        body = {"source_id": "booking-123", **EXAMPLE,
                "analysis_status": "demo", "ai_analysis": demo_analysis(EXAMPLE["message"]).model_dump()}
        headers = {"X-API-Token": "local-demo-token"}
        first = client.post("/leads", json=body, headers=headers)
        second = client.post("/leads", json=body, headers=headers)
        assert first.status_code == 201
        assert second.status_code == 200
        stored = client.get("/leads").json()
        assert len(stored) == 1
        assert stored[0]["ai_analysis"]["category"] == "move_out_cleaning"


def test_crm_requires_token(monkeypatch, tmp_path):
    monkeypatch.setenv("CRM_DB", str(tmp_path / "crm.db"))
    with TestClient(crm_app) as client:
        assert client.post("/leads", json={"source_id": "x", **EXAMPLE,
                    "analysis_status": "demo"}).status_code == 401


def test_ai_failure_does_not_block_crm_sync(monkeypatch, tmp_path):
    monkeypatch.setenv("INQUIRY_DB", str(tmp_path / "inquiries.db"))
    with TestClient(inquiry_app) as client:
        response = httpx.Response(201, request=httpx.Request("POST", "http://example.test"))
        with patch("servicesync.inquiry_api.analyze_message", new_callable=AsyncMock,
                   return_value=AnalysisOutcome("unavailable", None, "demo AI failure")):
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                       return_value=response) as delivery:
                result = client.post("/inquiries", json=EXAMPLE)
        assert result.json()["status"] == "synced"
        assert result.json()["analysis_status"] == "unavailable"
        assert result.json()["ai_analysis"] is None
        assert delivery.await_args.kwargs["json"]["analysis_status"] == "unavailable"


def test_missing_message_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("INQUIRY_DB", str(tmp_path / "inquiries.db"))
    with TestClient(inquiry_app) as client:
        short = client.post("/inquiries", json={**EXAMPLE, "message": "hi"})
        assert short.status_code == 422
