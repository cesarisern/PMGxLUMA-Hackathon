#!/usr/bin/env python3
"""
HTTP server for the Dynamic Voice Ad Generator frontend.

Serves index.html and orchestrates the pipeline via SSE:
  POST /api/run              -> start pipeline, returns { job_id }
  GET  /api/events/<job_id>  -> SSE stream of progress events
"""

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FRONTEND_DIR = Path(__file__).parent
REPO_ROOT = FRONTEND_DIR.parent
PORT = 8765

# Change to repo root so .env, data/, and all relative imports resolve correctly.
os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT))

import fetch_feeds
import generate_audio

_jobs: dict = {}
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Pipeline worker
# ---------------------------------------------------------------------------

def _emit(q: queue.Queue, stage: str, message: str, data=None) -> None:
    q.put({"stage": stage, "message": message, "data": data})


def _pipeline_worker(job_id: str, brand_url: str, campaign: str) -> None:
    q = _jobs[job_id]["queue"]
    emit = lambda stage, msg, data=None: _emit(q, stage, msg, data)

    try:
        # Stage 1 — fetch all four feeds (sequential)
        emit("feeds_start", "Fetching brand corpus, campaign context, trends and locations…")
        ns = argparse.Namespace(brand_url=brand_url, campaign=campaign, cached=False)
        feed_results = fetch_feeds.run(cached=False, args=ns)

        n = len(feed_results.get("locations", {}).get("locations", []))
        emit("feeds_done", f"Data ready — {n} location{'s' if n != 1 else ''} found", {"location_count": n})

        # Stage 2 — audio + image in parallel
        emit("gen_start", f"Starting audio generation for {n} locations and cover image in parallel…")

        audio_result: list = [None]
        image_url: list = [None]

        def _audio() -> None:
            try:
                emit("audio_start", "Submitting audio briefs to Audiostack…")
                results = generate_audio.run()
                audio_result[0] = results
                complete = sum(1 for r in results if r.get("status") == "complete")
                emit("audio_done", f"{complete} of {len(results)} ads rendered", results)
            except Exception as exc:
                emit("audio_error", f"Audio generation failed: {exc}")

        def _image() -> None:
            try:
                emit("image_start", "Generating cover image via Luma…")
                proc = subprocess.run(
                    [sys.executable, str(REPO_ROOT / "generate_image.py")],
                    capture_output=True,
                    text=True,
                    cwd=str(REPO_ROOT),
                )
                lines = [line.strip() for line in proc.stdout.split("\n") if line.strip()]
                url = lines[-1] if lines else ""
                if proc.returncode == 0 and url.startswith("http"):
                    image_url[0] = url
                    emit("image_done", "Cover image ready", {"url": url})
                else:
                    err = (proc.stderr or url or "Unknown error").strip()
                    emit("image_error", f"Image generation failed: {err}")
            except Exception as exc:
                emit("image_error", f"Image generation failed: {exc}")

        t1 = threading.Thread(target=_audio, daemon=True)
        t2 = threading.Thread(target=_image, daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        _jobs[job_id]["results"] = {"audio": audio_result[0], "image": image_url[0]}
        emit("done", "Pipeline complete", {"audio": audio_result[0], "image": image_url[0]})

    except Exception as exc:
        emit("error", f"Pipeline failed: {exc}")
    finally:
        q.put(None)  # sentinel — signals SSE handler to close stream


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # suppress access log

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._serve_file(FRONTEND_DIR / "index.html", "text/html; charset=utf-8")
        elif self.path.startswith("/api/events/"):
            self._sse(self.path.rsplit("/", 1)[-1])
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        if self.path != "/api/run":
            self.send_response(404)
            self.end_headers()
            return

        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n))
        except Exception:
            self._json({"error": "Invalid JSON body."}, 400)
            return

        brand_url = (body.get("brand_url") or "").strip()
        campaign = (body.get("campaign") or "").strip()

        if not brand_url or not campaign:
            self._json({"error": "brand_url and campaign are required."}, 400)
            return

        job_id = uuid.uuid4().hex[:8]
        with _lock:
            _jobs[job_id] = {"queue": queue.Queue(), "results": {}}

        threading.Thread(
            target=_pipeline_worker,
            args=(job_id, brand_url, campaign),
            daemon=True,
        ).start()

        self._json({"job_id": job_id})

    # ------------------------------------------------------------------

    def _serve_file(self, path: Path, mime: str) -> None:
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj: dict, status: int = 200) -> None:
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _sse(self, job_id: str) -> None:
        with _lock:
            job = _jobs.get(job_id)
        if not job:
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self._cors()
        self.end_headers()

        q = job["queue"]
        try:
            while True:
                try:
                    msg = q.get(timeout=25)
                    if msg is None:
                        break
                    self.wfile.write(f"data: {json.dumps(msg)}\n\n".encode())
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    server = ThreadingHTTPServer(("localhost", PORT), _Handler)
    print(f"Server running at http://localhost:{PORT}")
    server.serve_forever()
