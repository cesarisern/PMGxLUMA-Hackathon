import json
import os
import time
from pathlib import Path
from typing import Any, Callable

import requests

import db
from services import brief as brief_service

BASE = "https://v2.api.audio"
DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _headers() -> dict[str, str]:
    api_key = os.getenv("AUDIOSTACK_API_KEY")
    org_id = os.getenv("AUDIOSTACK_ORG_ID")
    if not api_key or not org_id:
        raise ValueError("AUDIOSTACK_API_KEY and AUDIOSTACK_ORG_ID must be set in .env")
    return {"x-api-key": api_key, "x-assume-org": org_id}


def _submit_brief(payload: dict[str, Any], headers: dict[str, str]) -> tuple[str, dict[str, Any]]:
    response = requests.post(f"{BASE}/creator/brief", headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    raw = response.json()
    audioforms = raw.get("data", {}).get("audioforms", [])
    if not audioforms:
        raise RuntimeError("AudioStack response did not include any audioforms.")
    return audioforms[0]["audioformId"], raw


def _poll(audioform_id: str, headers: dict[str, str], timeout: int = 180) -> dict[str, Any]:
    poll_headers = {**headers, "version": "4"}
    deadline = time.time() + timeout
    last_raw: dict[str, Any] = {}

    while time.time() < deadline:
        response = requests.get(f"{BASE}/audioforms/{audioform_id}", headers=poll_headers, timeout=60)
        if response.status_code == 202:
            last_raw = response.json() if response.content else {"statusCode": 202}
            time.sleep(3)
            continue
        if response.status_code == 200:
            raw = response.json()
            result = raw.get("data", {}).get("result", {})
            return {
                "status": "complete",
                "raw": raw,
                "deliveryUri": result.get("delivery", {}).get("uri"),
                "scriptText": result.get("assets", {}).get("tts0", {}).get("text"),
            }
        response.raise_for_status()
    return {"status": "timeout", "raw": last_raw, "deliveryUri": None, "scriptText": None}


def generate_for_locations(
    run_id: int,
    location_names: list[str],
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    db.init()
    headers = _headers()
    brand, context, trends, all_locations = brief_service.get_run_inputs(run_id)
    selected = [loc for loc in all_locations if loc["name"] in set(location_names)]
    if not selected:
        raise ValueError("No selected locations were found in this run.")

    results: list[dict[str, Any]] = []
    for loc in selected:
        payload = brief_service.make_brief(brand, context, trends, loc)
        result: dict[str, Any] = {
            "location": loc["name"],
            "status": "running",
            "request": {"url": f"{BASE}/creator/brief", "method": "POST", "body": payload},
        }
        if progress_cb:
            progress_cb(result)
        try:
            audioform_id, submit_raw = _submit_brief(payload, headers)
            poll_data = _poll(audioform_id, headers)
            status = poll_data["status"]
            result.update(
                {
                    "status": status,
                    "submitResponse": {"audioformId": audioform_id, "raw": submit_raw},
                    "pollResponse": poll_data,
                    "audioUrl": poll_data.get("deliveryUri"),
                    "audioform_id": audioform_id,
                    "audio_url": poll_data.get("deliveryUri") or "",
                }
            )
        except Exception as exc:
            result.update(
                {
                    "status": "error",
                    "error": str(exc),
                    "submitResponse": None,
                    "pollResponse": None,
                    "audioUrl": None,
                    "audioform_id": None,
                    "audio_url": "",
                }
            )
        results.append(result)
        if progress_cb:
            progress_cb(result)

    db_rows = [
        {
            "location": row["location"],
            "audioform_id": row.get("audioform_id"),
            "audio_url": row.get("audio_url"),
            "status": row["status"],
        }
        for row in results
    ]
    db.save_audio_outputs(run_id, db_rows)
    out_path = DATA_DIR / "audio_outputs.json"
    out_path.write_text(json.dumps(results, indent=2))
    return results
