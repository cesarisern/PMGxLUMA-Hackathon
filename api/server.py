import asyncio
import threading
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
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

app = FastAPI(title="Dynamic Voice API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

RUNS: dict[int, dict[str, Any]] = {}
AUDIO_STATE: dict[int, dict[str, Any]] = {}
IMAGE_STATE: dict[int, dict[str, Any]] = {}
VIDEO_STATE: dict[int, dict[str, Any]] = {}
STATE_LOCK = threading.Lock()


class RunCreateRequest(BaseModel):
    brand: str = Field(min_length=3)
    campaign: str = Field(min_length=3)


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
            "clipUrls": None,
            "prompt": None,
            "error": None,
        }

    async def run_image_task() -> None:
        # Phase 1: generate the static image.
        try:
            img_result = await asyncio.to_thread(image_service.generate_image, run_id)
            with STATE_LOCK:
                IMAGE_STATE[run_id]["imageUrl"] = img_result["imageUrl"]
                IMAGE_STATE[run_id]["prompt"] = img_result["prompt"]
                IMAGE_STATE[run_id]["status"] = "generating_clips"
        except Exception as exc:
            with STATE_LOCK:
                IMAGE_STATE[run_id]["status"] = "failed"
                IMAGE_STATE[run_id]["error"] = str(exc)
            return

        # Phase 2: generate Luma video clips from the image (runs while audio is in progress).
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

    asyncio.create_task(run_image_task())
    return {"runId": run_id, "status": "running"}


@app.get("/runs/{run_id}/image")
def get_image_result(run_id: int) -> dict[str, Any]:
    with STATE_LOCK:
        state = IMAGE_STATE.get(run_id)
    if not state:
        return {"runId": run_id, "status": "idle", "imageUrl": None, "clipUrls": None}
    return {
        "runId": run_id,
        "status": state["status"],
        "imageUrl": state.get("imageUrl"),
        "clipUrls": state.get("clipUrls"),
        "prompt": state.get("prompt"),
        "error": state.get("error"),
    }


@app.post("/runs/{run_id}/generate-video")
async def generate_video(run_id: int, body: GenerateVideoRequest) -> dict[str, Any]:
    if not body.imageUrl:
        raise HTTPException(status_code=400, detail="imageUrl is required")

    # Use pre-generated clips if the image task already completed them.
    with STATE_LOCK:
        clip_urls = IMAGE_STATE.get(run_id, {}).get("clipUrls")

    with STATE_LOCK:
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
    if not state:
        return {"runId": run_id, "status": "idle", "results": []}
    return {
        "runId": run_id,
        "status": state["status"],
        "results": state["results"],
        "error": state.get("error"),
    }
