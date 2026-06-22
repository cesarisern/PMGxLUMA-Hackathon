"""SQLite storage for pipeline feed data."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "pipeline.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init() -> None:
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            brand_url   TEXT NOT NULL,
            campaign    TEXT NOT NULL,
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS brand_corpus (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id      INTEGER REFERENCES runs(id),
            brand_id    TEXT,
            brand_name  TEXT,
            data        TEXT NOT NULL,
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS campaign_context (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id      INTEGER REFERENCES runs(id),
            query       TEXT,
            live_moment TEXT,
            data        TEXT NOT NULL,
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS trend_signal (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id          INTEGER REFERENCES runs(id),
            source          TEXT,
            peak_keyword    TEXT,
            traffic_signal  TEXT,
            data            TEXT NOT NULL,
            created_at      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS locations (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id          INTEGER REFERENCES runs(id),
            name            TEXT NOT NULL,
            location_type   TEXT,
            cta_suffix      TEXT,
            url             TEXT,
            created_at      TEXT NOT NULL
        );
        """)


def create_run(brand_url: str, campaign: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO runs (brand_url, campaign, created_at) VALUES (?, ?, ?)",
            (brand_url, campaign, _now()),
        )
        return cur.lastrowid


def save_brand(run_id: int, data: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO brand_corpus (run_id, brand_id, brand_name, data, created_at) VALUES (?, ?, ?, ?, ?)",
            (run_id, data.get("brand_id"), data.get("brand_name"), json.dumps(data), _now()),
        )


def save_context(run_id: int, data: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO campaign_context (run_id, query, live_moment, data, created_at) VALUES (?, ?, ?, ?, ?)",
            (run_id, data.get("query"), data.get("live_moment"), json.dumps(data), _now()),
        )


def save_trends(run_id: int, data: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO trend_signal (run_id, source, peak_keyword, traffic_signal, data, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, data.get("source"), data.get("peak_keyword"), data.get("traffic_signal"), json.dumps(data), _now()),
        )


def save_locations(run_id: int, data: dict) -> None:
    now = _now()
    with get_conn() as conn:
        for loc in data.get("locations", []):
            conn.execute(
                "INSERT INTO locations (run_id, name, location_type, cta_suffix, url, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, loc.get("name"), loc.get("type"), loc.get("cta_suffix"), loc.get("url"), now),
            )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
