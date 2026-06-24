"""
Generate localized audio ads from the 4 data feeds via Audiostack.

Loads brand_corpus, campaign_context, trend_signal, locations from the DB,
builds one /creator/brief per location, submits all concurrently, polls for results.

Usage:
    python generate_audio.py                  # latest DB run, all locations
    python generate_audio.py --limit 3        # first N (demo mode)
    python generate_audio.py --run-id 1       # specific run
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from dotenv import load_dotenv

import db

load_dotenv(override=True)  # .env wins over any stale key exported in the shell

BASE = "https://v2.api.audio"


def _headers() -> dict:
    key = os.getenv("AUDIOSTACK_API_KEY")
    org = os.getenv("AUDIOSTACK_ORG_ID")
    if not key or not org:
        sys.exit("Error: AUDIOSTACK_API_KEY and AUDIOSTACK_ORG_ID must be set in .env")
    return {"x-api-key": key, "x-assume-org": org}


def _poll(af_id: str, headers: dict, timeout: int = 180) -> dict | None:
    """Poll until complete. Returns a dict with url, script_text, tts_start, tts_duration."""
    h = {**headers, "version": "4"}
    for _ in range(timeout // 3):
        r = requests.get(f"{BASE}/audioforms/{af_id}", headers=h)
        if r.status_code == 200:
            result = r.json()["data"].get("result", {})
            url = result.get("delivery", {}).get("uri")
            if not url:
                return None

            # Extract script text from the first tts asset in the result.
            script_text = ""
            tts_start = 0.0
            tts_duration = 0.0
            assets = result.get("assets", {})
            tts_key = next((k for k, v in assets.items() if v.get("type") == "tts"), None)
            if tts_key:
                script_text = assets[tts_key].get("text", "")

            # The clip position and duration tell us exactly when in the final
            # mixed audio the voiceover starts and how long it runs.
            try:
                clip = (
                    result["production"]["arrangement"]["sections"][0]
                    ["layers"][0]["clips"][0]
                )
                tts_start = clip.get("position", 0.0)
                tts_duration = clip.get("duration", 0.0)
            except (KeyError, IndexError):
                pass

            return {
                "url":          url,
                "script_text":  script_text,
                "tts_start":    tts_start,
                "tts_duration": tts_duration,
            }
        elif r.status_code == 202:
            time.sleep(3)
        else:
            r.raise_for_status()
    return None


def _submit_brief(location: str, brief_body: dict, headers: dict) -> tuple:
    """Returns (location, audioform_id)."""
    r = requests.post(f"{BASE}/creator/brief", headers=headers, json=brief_body)
    r.raise_for_status()
    ads = r.json()["data"]["audioforms"]
    af_id = ads[0]["audioformId"]
    print(f"[audio] → {location}: {af_id}")
    return location, af_id


def run(run_id: int = None, limit: int = None) -> list:
    db.init()
    headers = _headers()
    conn = db.get_conn()

    if run_id is None:
        row = conn.execute("SELECT id FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            sys.exit("No runs found. Run fetch_feeds.py first.")
        run_id = row["id"]
    print(f"[audio] Run #{run_id}")

    brand   = json.loads(conn.execute("SELECT data FROM brand_corpus WHERE run_id=? ORDER BY id DESC LIMIT 1", (run_id,)).fetchone()["data"])
    context = json.loads(conn.execute("SELECT data FROM campaign_context WHERE run_id=? ORDER BY id DESC LIMIT 1", (run_id,)).fetchone()["data"])
    trends  = json.loads(conn.execute("SELECT data FROM trend_signal WHERE run_id=? ORDER BY id DESC LIMIT 1", (run_id,)).fetchone()["data"])

    rows = conn.execute("SELECT name, cta_suffix FROM locations WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
    locations = [dict(r) for r in rows]
    if limit:
        locations = locations[:limit]

    print(f"[audio] Generating {len(locations)} ads for '{brand['brand_name']}'...")

    trend_signal = trends.get("traffic_signal", "")
    description = (
        f"{context.get('campaign_angle', '')}. "
        f"{brand.get('mission', '')} "
        f"Trend: {trend_signal}."
    )[:500].strip()

    tone_parts = brand.get("tone_of_voice", [])
    tone = ", ".join(tone_parts) if isinstance(tone_parts, list) else str(tone_parts)

    def make_brief(loc: dict) -> dict:
        # `sounds` is omitted on purpose — the agentic engine then recommends
        # and adds an appropriate background track itself.
        return {
            "audioformVersion": "2",
            "brief": {
                "script": {
                    "productName":        brand["brand_name"],
                    "productDescription": description,
                    "lang":               "en",
                    "callToAction":       f"{brand.get('cta', '')} — {loc['cta_suffix']}",
                    "targetAudience":     brand.get("target_audience", ""),
                    "toneOfScript":       tone,
                },
                "voices": [{"accent": ["american"], "voicePreset": "expressive"}],
                "delivery": {
                    "loudnessPreset": "streaming",
                    "encoderPreset":  "wav",
                    "public":         True,
                },
            },
            "numAds": 1,
            "engine": "agentic",
        }

    # Submit all concurrently
    print(f"[audio] Submitting {len(locations)} briefs...")
    submitted = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futs = {
            pool.submit(_submit_brief, loc["name"], make_brief(loc), headers): loc["name"]
            for loc in locations
        }
        for fut in as_completed(futs):
            try:
                loc_name, af_id = fut.result()
                submitted[loc_name] = af_id
            except Exception as e:
                print(f"[audio] ✗ {futs[fut]}: submit failed — {e}")

    # Poll all concurrently
    print(f"\n[audio] Polling {len(submitted)} audioforms (concurrent)...")
    results = []

    def poll_one(loc_name: str, af_id: str) -> dict:
        data = _poll(af_id, headers)
        if data:
            print(f"[audio] ✓ {loc_name:30} {data['url']}")
        else:
            print(f"[audio] ✗ {loc_name} timed out")
        return {
            "location":     loc_name,
            "audioform_id": af_id,
            "audio_url":    data["url"] if data else "",
            "script_text":  data.get("script_text", "") if data else "",
            "tts_start":    data.get("tts_start", 0.0) if data else 0.0,
            "tts_duration": data.get("tts_duration", 0.0) if data else 0.0,
            "status":       "complete" if data else "timeout",
        }

    with ThreadPoolExecutor(max_workers=10) as pool:
        futs = [pool.submit(poll_one, loc, af_id) for loc, af_id in submitted.items()]
        for fut in as_completed(futs):
            results.append(fut.result())

    db.save_audio_outputs(run_id, results)

    out_path = Path(__file__).parent / "data" / "audio_outputs.json"
    out_path.write_text(json.dumps(results, indent=2))

    complete = sum(1 for r in results if r["status"] == "complete")
    print(f"\n[audio] {complete}/{len(results)} rendered → {out_path}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id",    type=int, help="DB run ID (default: latest)")
    parser.add_argument("--limit",     type=int, help="Max locations (demo mode)")
    args = parser.parse_args()
    run(run_id=args.run_id, limit=args.limit)
