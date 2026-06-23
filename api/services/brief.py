from typing import Any

import db


def get_run_inputs(run_id: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    with db.get_conn() as conn:
        brand_row = conn.execute(
            "SELECT data FROM brand_corpus WHERE run_id = ? ORDER BY id DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        context_row = conn.execute(
            "SELECT data FROM campaign_context WHERE run_id = ? ORDER BY id DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        trends_row = conn.execute(
            "SELECT data FROM trend_signal WHERE run_id = ? ORDER BY id DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        location_rows = conn.execute(
            "SELECT name, cta_suffix, location_type, url FROM locations WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()

    if not (brand_row and context_row and trends_row):
        raise ValueError("Feed data not ready for this run.")

    import json

    brand = json.loads(brand_row["data"])
    context = json.loads(context_row["data"])
    trends = json.loads(trends_row["data"])
    locations = [
        {
            "name": row["name"],
            "cta_suffix": row["cta_suffix"],
            "type": row["location_type"],
            "url": row["url"],
        }
        for row in location_rows
    ]
    return brand, context, trends, locations


def _build_description(brand: dict[str, Any], context: dict[str, Any], trends: dict[str, Any]) -> str:
    trend_signal = trends.get("traffic_signal", "")
    return (
        f"{context.get('campaign_angle', '')}. "
        f"{brand.get('mission', '')} "
        f"Trend: {trend_signal}."
    )[:500].strip()


def _build_tone(brand: dict[str, Any]) -> str:
    tone_parts = brand.get("tone_of_voice", [])
    if isinstance(tone_parts, list):
        return ", ".join(str(part) for part in tone_parts)
    return str(tone_parts)


def make_brief(brand: dict[str, Any], context: dict[str, Any], trends: dict[str, Any], loc: dict[str, Any]) -> dict[str, Any]:
    description = _build_description(brand, context, trends)
    tone = _build_tone(brand)
    return {
        "audioformVersion": "2",
        "brief": {
            "script": {
                "productName": brand.get("brand_name", ""),
                "productDescription": description,
                "lang": "en",
                "callToAction": f"{brand.get('cta', '')} — {loc.get('cta_suffix', '')}",
                "targetAudience": brand.get("target_audience", ""),
                "toneOfScript": tone,
            },
            "voices": [{"accent": ["american"], "voicePreset": "expressive"}],
            "delivery": {
                "loudnessPreset": "streaming",
                "encoderPreset": "wav",
                "public": True,
            },
        },
        "numAds": 1,
        "engine": "agentic",
    }


def build_preview_for_locations(run_id: int, selected_locations: list[str]) -> dict[str, Any]:
    brand, context, trends, all_locations = get_run_inputs(run_id)
    selected_set = {name.strip() for name in selected_locations if name.strip()}
    if not selected_set:
        raise ValueError("At least one location is required.")

    selected = [loc for loc in all_locations if loc["name"] in selected_set]
    if not selected:
        raise ValueError("None of the selected locations are available in this run.")

    previews: list[dict[str, Any]] = []
    for loc in selected:
        payload = make_brief(brand, context, trends, loc)
        script = payload["brief"]["script"]
        previews.append(
            {
                "location": loc["name"],
                "summary": (
                    f"{script['productName']} targeting {script['targetAudience']} "
                    f"with CTA '{script['callToAction']}'"
                ),
                "payload": payload,
            }
        )

    return {
        "runId": run_id,
        "shared": {
            "productName": brand.get("brand_name", ""),
            "productDescription": _build_description(brand, context, trends),
            "targetAudience": brand.get("target_audience", ""),
            "toneOfScript": _build_tone(brand),
        },
        "locations": previews,
    }
