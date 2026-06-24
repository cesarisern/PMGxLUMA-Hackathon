import asyncio
import threading
import sys
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Ensure repo root modules (db.py, fetch_feeds.py) are importable no matter where uvicorn starts.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import db
from services import audio as audio_service
from services import brief as brief_service
from services import feeds as feeds_service
from services import image as image_service
from services import video as video_service

load_dotenv(dotenv_path="../.env", override=True)

VIDEO_DIR = ROOT_DIR / "data" / "videos"
VIDEO_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_DIR = ROOT_DIR / "data" / "images"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Dynamic Voice API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static/videos", StaticFiles(directory=str(VIDEO_DIR)), name="static_videos")
app.mount("/static/images", StaticFiles(directory=str(IMAGE_DIR)), name="static_images")

RUNS: dict[int, dict[str, Any]] = {}
AUDIO_STATE: dict[int, dict[str, Any]] = {}
IMAGE_STATE: dict[int, dict[str, Any]] = {}
VIDEO_STATE: dict[int, dict[str, Any]] = {}
STATE_LOCK = threading.Lock()


class RunCreateRequest(BaseModel):
    brand: str = Field(min_length=3)
    campaign: str = Field(min_length=3)


class SuggestCampaignRequest(BaseModel):
    brand: str = Field(min_length=3)


class GenerateRequest(BaseModel):
    locations: list[str]


class GenerateVideoRequest(BaseModel):
    imageUrl: str
    brandUrl: str = ""


@app.on_event("startup")
async def startup() -> None:
    db.init()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/suggest-campaign-name")
async def suggest_campaign_name(body: SuggestCampaignRequest) -> dict[str, str]:
    import os
    import re
    from anthropic import Anthropic
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = await asyncio.to_thread(
        lambda: client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system=(
                "You write campaign descriptions for localized audio/radio ads. "
                "Output exactly 2–3 plain sentences with no headers, bullets, or markdown. "
                "Be specific: campaign moment, target audience, and key message."
            ),
            messages=[{
                "role": "user",
                "content": f"Brand: {body.brand}\n\nWrite a campaign description.",
            }],
        )
    )
    text = re.sub(r"^#+\s.*\n?", "", response.content[0].text, flags=re.MULTILINE).strip()
    return {"suggestion": text}


@app.get("/proxy-download")
async def proxy_download(url: str = Query(...), filename: str = Query(default="download")) -> Response:
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        resp = await client.get(url)
    return Response(
        content=resp.content,
        media_type=resp.headers.get("content-type", "application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _maybe_start_video(run_id: int) -> None:
    """Auto-start video generation when both audio and image+clips are ready."""
    with STATE_LOCK:
        audio_done = AUDIO_STATE.get(run_id, {}).get("status") == "complete"
        img_st = dict(IMAGE_STATE.get(run_id, {}))
        clips_done = img_st.get("status") == "complete"
        already_started = run_id in VIDEO_STATE

        if audio_done and clips_done and not already_started:
            VIDEO_STATE[run_id] = {"status": "running", "results": [], "error": None}
            should_start = True
        else:
            should_start = False

    if not should_start:
        return

    image_url: str = img_st.get("imageUrl", "")
    clip_urls: list[str] | None = img_st.get("clipUrls")
    brand_url: str = RUNS.get(run_id, {}).get("brand", "")

    async def _video_task() -> None:
        try:
            results = await asyncio.to_thread(
                video_service.generate, run_id, image_url, brand_url, clip_urls
            )
            with STATE_LOCK:
                VIDEO_STATE[run_id]["status"] = "complete"
                VIDEO_STATE[run_id]["results"] = results
        except Exception as exc:
            with STATE_LOCK:
                VIDEO_STATE[run_id]["status"] = "failed"
                VIDEO_STATE[run_id]["error"] = str(exc)

    asyncio.create_task(_video_task())


@app.post("/runs")
async def create_run(body: RunCreateRequest) -> dict[str, Any]:
    brand = body.brand.strip()
    campaign = body.campaign.strip()
    if len(brand) < 3 or len(campaign) < 3:
        raise HTTPException(status_code=422, detail="brand and campaign must be at least 3 chars")

    run_id = feeds_service.get_next_run_id()
    with STATE_LOCK:
        RUNS[run_id] = {"status": "running", "brand": brand, "campaign": campaign, "error": None}

    async def run_task() -> None:
        # Stage 1: feeds
        try:
            await asyncio.to_thread(feeds_service.run_fetch_pipeline, brand, campaign)
            with STATE_LOCK:
                if run_id in RUNS:
                    RUNS[run_id]["status"] = "complete"
        except Exception as exc:
            with STATE_LOCK:
                if run_id in RUNS:
                    RUNS[run_id]["status"] = "failed"
                    RUNS[run_id]["error"] = str(exc)
            return

        # Stage 2: image (auto-triggered after feeds)
        with STATE_LOCK:
            IMAGE_STATE[run_id] = {
                "status": "running",
                "imageUrl": None,
                "imageUrl1x1": None,
                "clipUrls": None,
                "prompt": None,
                "error": None,
            }
        try:
            img_result = await asyncio.to_thread(image_service.generate, run_id)
            with STATE_LOCK:
                IMAGE_STATE[run_id]["imageUrl"] = img_result["imageUrl"]
                IMAGE_STATE[run_id]["imageUrl1x1"] = img_result.get("imageUrl1x1")
                IMAGE_STATE[run_id]["prompt"] = img_result["prompt"]
                IMAGE_STATE[run_id]["status"] = "generating_clips"
        except Exception as exc:
            with STATE_LOCK:
                IMAGE_STATE[run_id]["status"] = "failed"
                IMAGE_STATE[run_id]["error"] = str(exc)
            return

        # Stage 3: clips (auto-triggered after image)
        try:
            clip_urls = await asyncio.to_thread(
                image_service.generate_clips,
                img_result["imageUrl"],
                img_result["context"],
                img_result["brand_colours"],
                img_result.get("target_audience", ""),
            )
            with STATE_LOCK:
                IMAGE_STATE[run_id]["status"] = "complete"
                IMAGE_STATE[run_id]["clipUrls"] = clip_urls
        except Exception as exc:
            with STATE_LOCK:
                IMAGE_STATE[run_id]["status"] = "clips_failed"
                IMAGE_STATE[run_id]["error"] = str(exc)
            return

        await _maybe_start_video(run_id)

    asyncio.create_task(run_task())
    return {"runId": run_id, "status": "running"}


@app.get("/runs/{run_id}")
def get_run(run_id: int) -> dict[str, Any]:
    run_row = feeds_service.get_run_row(run_id)
    with STATE_LOCK:
        state = RUNS.get(run_id, {})

    if not run_row and not state:
        raise HTTPException(status_code=404, detail="Run not found")

    feeds = feeds_service.get_feed_snapshot(run_id)
    has_all = all(feeds.get(key) is not None for key in ("brand", "context", "trends", "locations"))
    status = state.get("status") or ("complete" if has_all else "running")
    if state.get("status") == "failed":
        status = "failed"

    brand = (run_row or {}).get("brand_url") or state.get("brand", "")
    campaign = (run_row or {}).get("campaign") or state.get("campaign", "")

    return {
        "runId": run_id,
        "brand": brand,
        "campaign": campaign,
        "status": status,
        "feeds": feeds,
        "error": state.get("error"),
    }


@app.get("/runs/{run_id}/brief-preview")
def get_brief_preview(run_id: int, locations: str = Query(default="")) -> dict[str, Any]:
    selected = [item.strip() for item in locations.split(",") if item.strip()]
    try:
        return brief_service.build_preview_for_locations(run_id, selected)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/runs/{run_id}/generate")
async def generate_audio(run_id: int, body: GenerateRequest) -> dict[str, Any]:
    selected = [name.strip() for name in body.locations if name.strip()]
    if not selected:
        raise HTTPException(status_code=400, detail="At least one location is required")

    with STATE_LOCK:
        AUDIO_STATE[run_id] = {"status": "running", "results": [], "error": None}

    def progress_cb(result: dict[str, Any]) -> None:
        with STATE_LOCK:
            if run_id not in AUDIO_STATE:
                return
            current = AUDIO_STATE[run_id]["results"]
            existing_idx = next((i for i, item in enumerate(current) if item["location"] == result["location"]), None)
            if existing_idx is None:
                current.append(result)
            else:
                current[existing_idx] = result

    async def run_audio_task() -> None:
        try:
            results = await asyncio.to_thread(
                audio_service.generate_for_locations,
                run_id,
                selected,
                progress_cb,
            )
            with STATE_LOCK:
                AUDIO_STATE[run_id]["status"] = "complete"
                AUDIO_STATE[run_id]["results"] = results
        except Exception as exc:
            with STATE_LOCK:
                AUDIO_STATE[run_id]["status"] = "failed"
                AUDIO_STATE[run_id]["error"] = str(exc)
            return

        await _maybe_start_video(run_id)

    asyncio.create_task(run_audio_task())
    return {"runId": run_id, "status": "running"}


@app.get("/runs/{run_id}/audio")
def get_audio_results(run_id: int) -> dict[str, Any]:
    with STATE_LOCK:
        state = AUDIO_STATE.get(run_id)
    if not state:
        return {"runId": run_id, "status": "idle", "results": []}
    return {
        "runId": run_id,
        "status": state["status"],
        "results": state["results"],
        "error": state.get("error"),
    }


@app.post("/runs/{run_id}/generate-image")
async def generate_image(run_id: int) -> dict[str, Any]:
    with STATE_LOCK:
        IMAGE_STATE[run_id] = {
            "status": "running",
            "imageUrl": None,
            "imageUrl1x1": None,
            "clipUrls": None,
            "prompt": None,
            "error": None,
        }

    async def run_image_task() -> None:
        try:
            img_result = await asyncio.to_thread(image_service.generate, run_id)
            with STATE_LOCK:
                IMAGE_STATE[run_id]["imageUrl"] = img_result["imageUrl"]
                IMAGE_STATE[run_id]["imageUrl1x1"] = img_result.get("imageUrl1x1")
                IMAGE_STATE[run_id]["prompt"] = img_result["prompt"]
                IMAGE_STATE[run_id]["status"] = "generating_clips"
        except Exception as exc:
            with STATE_LOCK:
                IMAGE_STATE[run_id]["status"] = "failed"
                IMAGE_STATE[run_id]["error"] = str(exc)
            return

        try:
            clip_urls = await asyncio.to_thread(
                image_service.generate_clips,
                img_result["imageUrl"],
                img_result["context"],
                img_result["brand_colours"],
                img_result.get("target_audience", ""),
            )
            with STATE_LOCK:
                IMAGE_STATE[run_id]["status"] = "complete"
                IMAGE_STATE[run_id]["clipUrls"] = clip_urls
        except Exception as exc:
            with STATE_LOCK:
                IMAGE_STATE[run_id]["status"] = "clips_failed"
                IMAGE_STATE[run_id]["error"] = str(exc)

        await _maybe_start_video(run_id)

    asyncio.create_task(run_image_task())
    return {"runId": run_id, "status": "running"}


@app.get("/runs/{run_id}/image")
def get_image_result(run_id: int) -> dict[str, Any]:
    with STATE_LOCK:
        state = IMAGE_STATE.get(run_id)
    if not state:
        return {"runId": run_id, "status": "idle", "imageUrl": None, "imageUrl1x1": None, "clipUrls": None}
    return {
        "runId": run_id,
        "status": state["status"],
        "imageUrl": state.get("imageUrl"),
        "imageUrl1x1": state.get("imageUrl1x1"),
        "clipUrls": state.get("clipUrls"),
        "prompt": state.get("prompt"),
        "error": state.get("error"),
    }


@app.post("/runs/{run_id}/generate-video")
async def generate_video(run_id: int, body: GenerateVideoRequest) -> dict[str, Any]:
    if not body.imageUrl:
        raise HTTPException(status_code=400, detail="imageUrl is required")

    with STATE_LOCK:
        clip_urls = IMAGE_STATE.get(run_id, {}).get("clipUrls")
        VIDEO_STATE[run_id] = {"status": "running", "results": [], "error": None}

    async def run_video_task() -> None:
        try:
            results = await asyncio.to_thread(
                video_service.generate,
                run_id,
                body.imageUrl,
                body.brandUrl,
                clip_urls,
            )
            with STATE_LOCK:
                VIDEO_STATE[run_id]["status"] = "complete"
                VIDEO_STATE[run_id]["results"] = results
        except Exception as exc:
            with STATE_LOCK:
                VIDEO_STATE[run_id]["status"] = "failed"
                VIDEO_STATE[run_id]["error"] = str(exc)

    asyncio.create_task(run_video_task())
    return {"runId": run_id, "status": "running"}


@app.get("/runs/{run_id}/video")
def get_video_results(run_id: int) -> dict[str, Any]:
    with STATE_LOCK:
        state = VIDEO_STATE.get(run_id)

    if state:
        raw_results = state["results"]
        status = state["status"]
        error = state.get("error")
    else:
        # Fall back to DB for results from previous server sessions.
        db_rows = db.get_video_outputs(run_id)
        if not db_rows:
            return {"runId": run_id, "status": "idle", "results": []}
        raw_results = db_rows
        all_statuses = {r["status"] for r in db_rows}
        status = "complete" if all_statuses <= {"complete"} else "failed" if "failed" in all_statuses else "complete"
        error = None

    def _enrich(r: dict[str, Any]) -> dict[str, Any]:
        filename = r.get("video_filename", "")
        return {
            **r,
            "videoUrl": f"/static/videos/{filename}" if filename else None,
        }

    return {
        "runId": run_id,
        "status": status,
        "results": [_enrich(r) for r in raw_results],
        "error": error,
    }
