"""Incoming service requests: save first, optionally enrich, send to mock CRM."""
import json
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from servicesync.ai_service import analyze_message
from servicesync.models import NewInquiry
from servicesync.storage import connect, ensure_columns


def database() -> sqlite3.Connection:
    return connect("INQUIRY_DB", "data/inquiries.db")


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def public_record(row: sqlite3.Row | dict) -> dict:
    """Return a safe, display-ready record with derived review flags.

    AI output is advisory: a category mismatch never changes the original
    submitted service or automatically approves a customer request.
    """
    result = dict(row)
    analysis_json = result.pop("ai_analysis_json", None)
    result["ai_analysis"] = json.loads(analysis_json) if analysis_json else None
    flags: list[str] = []
    analysis = result["ai_analysis"]
    if result.get("analysis_status") == "unavailable":
        flags.append("ai_unavailable")
    if analysis:
        category = analysis.get("category")
        if category == "other":
            flags.append("unclassified")
        elif category and category != result.get("service_type"):
            flags.append("service_mismatch")
        if analysis.get("needs_review"):
            flags.append("ai_review")
    result["review_flags"] = flags
    result["needs_attention"] = bool(flags)
    return result


def find_inquiry(inquiry_id: str) -> dict | None:
    with database() as db:
        row = db.execute("SELECT * FROM inquiries WHERE id = ?", (inquiry_id,)).fetchone()
    return public_record(row) if row else None


def update_delivery(inquiry_id: str, status: str, error: str | None) -> None:
    with database() as db:
        db.execute(
            """UPDATE inquiries SET status = ?, last_error = ?,
               delivery_attempts = delivery_attempts + 1 WHERE id = ?""",
            (status, error, inquiry_id),
        )


async def sync_to_crm(inquiry_id: str) -> dict:
    inquiry = find_inquiry(inquiry_id)
    if not inquiry:
        raise HTTPException(status_code=404, detail="Inquiry not found")
    if inquiry["status"] == "synced":
        return inquiry

    # The target host and credentials are set server-side, never user-provided.
    endpoint = os.getenv("CRM_URL", "http://127.0.0.1:8001/leads")
    token = os.getenv("CRM_API_TOKEN", "local-demo-token")
    payload = {
        "source_id": inquiry["id"],
        "customer_name": inquiry["customer_name"],
        "service_type": inquiry["service_type"],
        "postal_code": inquiry["postal_code"],
        "message": inquiry["message"],
        "analysis_status": inquiry["analysis_status"],
        "ai_analysis": inquiry["ai_analysis"],
    }

    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            response = await client.post(endpoint, json=payload, headers={"X-API-Token": token})
            response.raise_for_status()
    except httpx.HTTPError as error:
        update_delivery(inquiry_id, "failed", type(error).__name__)
    else:
        update_delivery(inquiry_id, "synced", None)

    return find_inquiry(inquiry_id)


@asynccontextmanager
async def lifespan(_: FastAPI):
    with database() as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS inquiries (
               id TEXT PRIMARY KEY,
               customer_name TEXT NOT NULL,
               service_type TEXT NOT NULL,
               postal_code TEXT NOT NULL,
               message TEXT NOT NULL DEFAULT '',
               created_at TEXT NOT NULL,
               status TEXT NOT NULL,
               delivery_attempts INTEGER NOT NULL DEFAULT 0,
               last_error TEXT,
               analysis_status TEXT NOT NULL DEFAULT 'unavailable',
               ai_analysis_json TEXT,
               ai_error TEXT
            )"""
        )
        # Small local schema migration for databases from the starter project.
        ensure_columns(db, "inquiries", {
            "message": "TEXT NOT NULL DEFAULT ''",
            "analysis_status": "TEXT NOT NULL DEFAULT 'unavailable'",
            "ai_analysis_json": "TEXT",
            "ai_error": "TEXT",
        })
    yield


app = FastAPI(title="ServiceSync AI – Inquiry API", lifespan=lifespan)

# Serve the dashboard from the same origin as the API. No CORS or frontend
# secrets required; keep uvicorn bound to 127.0.0.1 for this local prototype.
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/inquiries", status_code=201)
async def submit_inquiry(inquiry: NewInquiry):
    inquiry_id = str(uuid.uuid4())
    with database() as db:
        db.execute(
            """INSERT INTO inquiries
            (id, customer_name, service_type, postal_code, message, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
            (inquiry_id, inquiry.customer_name, inquiry.service_type,
             inquiry.postal_code, inquiry.message, now_utc()),
        )

    # AI enrichment is optional. This happens AFTER persisting the request.
    outcome = await analyze_message(inquiry.message)
    with database() as db:
        db.execute(
            """UPDATE inquiries SET analysis_status=?, ai_analysis_json=?, ai_error=?
               WHERE id=?""",
            (outcome.status, outcome.analysis.model_dump_json() if outcome.analysis else None,
             outcome.error, inquiry_id),
        )
    # The CRM is contacted even when model analysis failed.
    return await sync_to_crm(inquiry_id)


@app.get("/inquiries")
def list_inquiries():
    with database() as db:
        rows = db.execute("SELECT * FROM inquiries ORDER BY created_at DESC").fetchall()
    return [public_record(row) for row in rows]


@app.post("/inquiries/{inquiry_id}/retry")
async def retry_one(inquiry_id: str):
    return await sync_to_crm(inquiry_id)


@app.post("/retry-failed")
async def retry_failed():
    with database() as db:
        rows = db.execute("SELECT id FROM inquiries WHERE status != 'synced'").fetchall()
    results = [await sync_to_crm(row["id"]) for row in rows]
    return {
        "attempted": len(results),
        "synced": sum(item["status"] == "synced" for item in results),
        "still_failed": sum(item["status"] != "synced" for item in results),
    }


@app.get("/report")
def report():
    with database() as db:
        statuses = db.execute(
            "SELECT status, COUNT(*) AS total FROM inquiries GROUP BY status"
        ).fetchall()
        analyses = db.execute(
            "SELECT analysis_status, COUNT(*) AS total FROM inquiries GROUP BY analysis_status"
        ).fetchall()
        total_attempts = db.execute(
            "SELECT COALESCE(SUM(delivery_attempts), 0) FROM inquiries"
        ).fetchone()[0]
    return {
        "status_counts": {row["status"]: row["total"] for row in statuses},
        "analysis_counts": {row["analysis_status"]: row["total"] for row in analyses},
        "delivery_attempts": total_attempts,
    }
