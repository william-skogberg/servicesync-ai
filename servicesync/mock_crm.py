"""Standalone local mock CRM; never connect it to a real customer database."""
import json
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException, Response

from servicesync.models import CRMLead
from servicesync.storage import connect, ensure_columns


def database() -> sqlite3.Connection:
    return connect("CRM_DB", "data/crm.db")


@asynccontextmanager
async def lifespan(_: FastAPI):
    with database() as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS leads (
                source_id TEXT PRIMARY KEY,
                customer_name TEXT NOT NULL,
                service_type TEXT NOT NULL,
                postal_code TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                analysis_status TEXT NOT NULL DEFAULT 'unavailable',
                ai_analysis_json TEXT,
                received_at TEXT NOT NULL
            )"""
        )
        ensure_columns(db, "leads", {
            "message": "TEXT NOT NULL DEFAULT ''",
            "analysis_status": "TEXT NOT NULL DEFAULT 'unavailable'",
            "ai_analysis_json": "TEXT",
        })
    yield


app = FastAPI(title="ServiceSync AI – Mock CRM", lifespan=lifespan)


@app.post("/leads")
def create_lead(lead: CRMLead, response: Response,
                x_api_token: str | None = Header(default=None)):
    expected = os.getenv("CRM_API_TOKEN", "local-demo-token")
    if x_api_token != expected:
        raise HTTPException(status_code=401, detail="Invalid demo API token")

    with database() as db:
        cursor = db.execute(
            """INSERT OR IGNORE INTO leads
               (source_id, customer_name, service_type, postal_code,
                message, analysis_status, ai_analysis_json, received_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (lead.source_id, lead.customer_name, lead.service_type,
             lead.postal_code, lead.message, lead.analysis_status,
             lead.ai_analysis.model_dump_json() if lead.ai_analysis else None,
             datetime.now(timezone.utc).isoformat()),
        )
        inserted = cursor.rowcount > 0
    response.status_code = 201 if inserted else 200
    return {"source_id": lead.source_id, "created": inserted}


@app.get("/leads")
def list_leads():
    with database() as db:
        rows = db.execute("SELECT * FROM leads ORDER BY received_at DESC").fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["ai_analysis"] = json.loads(item.pop("ai_analysis_json")) if item["ai_analysis_json"] else None
        result.append(item)
    return result
