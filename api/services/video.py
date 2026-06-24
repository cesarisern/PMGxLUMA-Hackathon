import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import db

ROOT_DIR = Path(__file__).resolve().parents[2]

# Subtitles span from the end of the static hold through most of the montage.
_CAPTION_START = 3.0
_CAPTION_DURATION = 22.0


def _get_audio_results(run_id: int) -> list[dict[str, Any]]:
    db.init()
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT location, audioform_id, audio_url, status FROM audio_outputs"
            " WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
    audio_rows = [dict(row) for row in rows]

    # Enrich each row with brief-derived caption text so subtitles work without
    # waiting for the full AudioStack transcript.
    try:
        from services import brief as brief_service
        brand, context, trends, all_locations = brief_service.get_run_inputs(run_id)
        locs_by_name = {loc["name"]: loc for loc in all_locations}
        for row in audio_rows:
            loc = locs_by_name.get(
                row["location"],
                {"name": row["location"], "cta_suffix": "", "url": ""},
            )
            brief_payload = brief_service.make_brief(brand, context, trends, loc)
            script = brief_payload.get("brief", {}).get("script", {})
            name = script.get("productName", "")
            cta = script.get("callToAction", "")
            row["script_text"] = f"{name}. {cta}".strip(". ") if (name or cta) else ""
            row["tts_start"] = _CAPTION_START
            row["tts_duration"] = _CAPTION_DURATION
    except Exception as exc:
        print(f"[video-service] Could not enrich audio with brief data: {exc}")

    return audio_rows


def generate(
    run_id: int,
    image_url: str,
    brand_url: str = "",
    clip_urls: list[str] | None = None,
) -> list[dict[str, Any]]:
    audio_results = _get_audio_results(run_id)
    if not audio_results:
        raise ValueError("No audio outputs found for this run. Generate audio first.")

    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))
    import generate_video_from_image

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(audio_results, f)
        tmp_path = Path(f.name)

    try:
        results = generate_video_from_image.run(
            image_url,
            tmp_path,
            brand_url,
            pregenerated_clip_urls=clip_urls,
        )
    except SystemExit as exc:
        raise RuntimeError(f"Video generation failed: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    db.save_video_outputs(run_id, results)
    return results
