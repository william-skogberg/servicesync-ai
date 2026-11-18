"""Dashboard tests: local assets and review flags, with no actual AI/API calls."""
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from servicesync.ai_service import AnalysisOutcome
from servicesync.inquiry_api import app


EXAMPLE = {
    "customer_name": "Demo Customer",
    "service_type": "home_cleaning",  # intentionally disagrees with the message
    "postal_code": "00100",
    "message": "I need move-out cleaning next Friday for an 85 m2 flat.",
}


def successful_crm_response():
    return httpx.Response(201, request=httpx.Request("POST", "http://crm.test/leads"))


def test_dashboard_is_served_with_local_assets(monkeypatch, tmp_path):
    monkeypatch.setenv("INQUIRY_DB", str(tmp_path / "inquiries.db"))
    with TestClient(app) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "Service overview" in home.text
        js = client.get("/static/app.js")
        css = client.get("/static/style.css")
        assert js.status_code == 200
        assert css.status_code == 200
        assert "POST" not in home.text or "new-inquiry-form" in home.text
        assert "fetch(path" in js.text


def test_ai_service_mismatch_is_flagged_without_changing_selected_service(monkeypatch, tmp_path):
    monkeypatch.setenv("INQUIRY_DB", str(tmp_path / "inquiries.db"))
    monkeypatch.setenv("AI_MODE", "demo")
    with TestClient(app) as client:
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=successful_crm_response()):
            result = client.post("/inquiries", json=EXAMPLE)
        assert result.status_code == 201
        data = result.json()
        assert data["status"] == "synced"
        assert data["service_type"] == "home_cleaning"
        assert data["ai_analysis"]["category"] == "move_out_cleaning"
        assert data["needs_attention"] is True
        assert "service_mismatch" in data["review_flags"]
        stored = client.get("/inquiries").json()[0]
        assert "service_mismatch" in stored["review_flags"]


def test_matching_category_not_falsely_flagged_as_mismatch(monkeypatch, tmp_path):
    monkeypatch.setenv("INQUIRY_DB", str(tmp_path / "inquiries.db"))
    monkeypatch.setenv("AI_MODE", "demo")
    matching = {**EXAMPLE, "service_type": "move_out_cleaning"}
    with TestClient(app) as client:
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=successful_crm_response()):
            data = client.post("/inquiries", json=matching).json()
    assert "service_mismatch" not in data["review_flags"]
    assert "ai_review" in data["review_flags"]  # demo mode always requests review


def test_ai_fallback_generates_review_flag_without_blocking_delivery(monkeypatch, tmp_path):
    monkeypatch.setenv("INQUIRY_DB", str(tmp_path / "inquiries.db"))
    with TestClient(app) as client:
        with patch("servicesync.inquiry_api.analyze_message", new_callable=AsyncMock,
                   return_value=AnalysisOutcome("unavailable", None, "TestFailure")):
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=successful_crm_response()):
                data = client.post("/inquiries", json=EXAMPLE).json()
    assert data["status"] == "synced"
    assert data["analysis_status"] == "unavailable"
    assert data["review_flags"] == ["ai_unavailable"]
    assert data["needs_attention"] is True
