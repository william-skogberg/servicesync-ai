"""Shared SQLite helper for both local services."""
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # Reads .env locally; never commit .env to GitHub.


def connect(env_name: str, default_path: str) -> sqlite3.Connection:
    path = Path(os.getenv(env_name, default_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    return db


def ensure_columns(db: sqlite3.Connection, table: str, new_columns: dict[str, str]):
    """Tiny, fixed-schema migration for our local SQLite demo only."""
    existing = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
    for name, definition in new_columns.items():
        if name not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
