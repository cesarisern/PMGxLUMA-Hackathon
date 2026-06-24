import argparse
import json
from pathlib import Path
from typing import Any

import db
import fetch_feeds

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def run_fetch_pipeline(brand: str, campaign: str) -> dict[str, Any]:
    args = argparse.Namespace(brand_url=brand, campaign=campaign, cached=False)
    return fetch_feeds.run(cached=False, args=args)


def get_next_run_id() -> int:
    db.init()
    with db.get_conn() as conn:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS id FROM runs").fetchone()
        return int(row["id"])


def get_run_row(run_id: int) -> dict[str, Any] | None:
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT id, brand_url, campaign, created_at FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        return dict(row) if row else None


def _latest_json_from_table(run_id: int, table_name: str) -> dict[str, Any] | None:
    with db.get_conn() as conn:
        row = conn.execute(
            f"SELECT data FROM {table_name} WHERE run_id = ? ORDER BY id DESC LIMIT 1",
            (run_id,),
        ).fetchone()
    if not row:
        return None
    return json.loads(row["data"])


def _locations_from_db(run_id: int) -> dict[str, Any] | None:
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT name, location_type, cta_suffix, url FROM locations WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
    if not rows:
        return None
    locations = [
        {
            "name": row["name"],
            "type": row["location_type"],
            "cta_suffix": row["cta_suffix"],
            "url": row["url"],
        }
        for row in rows
    ]
    return {"locations": locations, "count": len(locations)}


def _fallback_json(file_name: str) -> dict[str, Any] | None:
    path = DATA_DIR / file_name
    if not path.exists():
        return None
    return json.loads(path.read_text())


def get_feed_snapshot(run_id: int) -> dict[str, Any]:
    brand_data = _latest_json_from_table(run_id, "brand_corpus") or _fallback_json("brand_corpus.json")
    context_data = _latest_json_from_table(run_id, "campaign_context") or _fallback_json("campaign_context.json")
    trends_data = _latest_json_from_table(run_id, "trend_signal") or _fallback_json("trend_signal.json")
    locations_data = _locations_from_db(run_id)
    if not locations_data:
        fallback_locations = _fallback_json("locations.json")
        if fallback_locations:
            fallback_list = fallback_locations.get("locations", [])
            locations_data = {"locations": fallback_list, "count": len(fallback_list)}

    return {
        "brand": {"status": "complete", "data": brand_data} if brand_data else None,
        "context": {"status": "complete", "data": context_data} if context_data else None,
        "trends": {"status": "complete", "data": trends_data} if trends_data else None,
        "locations": {"status": "complete", "data": locations_data, "count": locations_data["count"]}
        if locations_data
        else None,
    }
