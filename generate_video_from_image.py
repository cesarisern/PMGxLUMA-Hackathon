"""
Generate social-media MP4 videos from a Luma image URL + Audiostack audio outputs.

For each completed audio ad, this script:
  1. Generates a 5-second Ray-3.2 looping video clip (9:16) anchored to the source image.
  2. Loops that clip to 30 seconds with ffmpeg.
  3. Generates a timed SRT caption file from the Audiostack script text and timing metadata.
  4. Muxes video + audio + burned-in captions into a social-media-ready MP4.

Caption timing comes directly from the Audiostack audioform response (no ML required):
  - script_text  — the exact generated voiceover text
  - tts_start    — when in the final audio the voiceover begins (seconds)
  - tts_duration — how long the voiceover runs (seconds)

Sentences are split on punctuation and their durations are distributed proportionally
to character count, which is accurate enough for TTS output.

Outputs are written to data/videos/ and indexed in data/video_outputs.json.

Usage:
    python generate_video_from_image.py <image_url>
    python generate_video_from_image.py <image_url> --audio-file path/to/audio_outputs.json
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from luma_agents import Luma

load_dotenv()

client = Luma()

AUDIO_OUTPUTS_FILE = Path(__file__).parent / "data" / "audio_outputs.json"
VIDEO_DIR = Path(__file__).parent / "data" / "videos"
TARGET_DURATION = 30  # seconds


def _generate_luma_clip(image_url: str) -> str:
    """Submit a Ray-3.2 image-to-video generation and return the output URL."""
    generation = client.generations.create(
        prompt=(
            "Cinematic camera motion — slow parallax drift, subtle zoom, atmospheric depth. "
            "Dynamic and visually engaging throughout. Premium lifestyle aesthetic."
        ),
        type="video",
        model="ray-3.2",
        aspect_ratio="9:16",
        video={
            "start_frame": {"url": image_url},
            "loop": True,
            "duration": "5s",
        },
    )
    print(f"[video] Submitted Luma generation {generation.id}")

    while generation.state not in ("completed", "failed"):
        time.sleep(5)
        generation = client.generations.get(generation.id)
        print(f"[video] State: {generation.state}")

    if generation.state != "completed":
        raise RuntimeError(
            f"Luma video generation failed: {generation.failure_reason} ({generation.failure_code})"
        )

    return generation.output[0].url


def _download(url: str, dest: Path) -> None:
    urllib.request.urlretrieve(url, str(dest))


def _fmt_srt_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t % 1) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _write_srt(script_text: str, tts_start: float, tts_duration: float, srt_path: Path) -> bool:
    """
    Write an SRT file from Audiostack script timing metadata.

    Splits the script on sentence boundaries and distributes duration
    proportionally to character count. Returns True if any segments were written.
    """
    if not script_text or tts_duration <= 0:
        return False

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", script_text) if s.strip()]
    if not sentences:
        return False

    total_chars = sum(len(s) for s in sentences)
    lines = []
    t = tts_start
    for i, sentence in enumerate(sentences, 1):
        seg_duration = tts_duration * (len(sentence) / total_chars)
        end_t = t + seg_duration
        lines += [str(i), f"{_fmt_srt_time(t)} --> {_fmt_srt_time(end_t)}", sentence, ""]
        t = end_t

    srt_path.write_text("\n".join(lines), encoding="utf-8")
    return True


def _loop_to_duration(src: Path, dest: Path, target_secs: int) -> None:
    """Re-encode src video looped to fill target_secs, no audio track."""
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-stream_loop", "-1",
            "-i", str(src),
            "-t", str(target_secs),
            "-an",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            "-crf", "23",
            str(dest),
        ],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg loop failed: {result.stderr.decode()[-300:]}")


def _combine(
    video: Path,
    audio_url: str,
    output: Path,
    script_text: str = "",
    tts_start: float = 0.0,
    tts_duration: float = 0.0,
) -> None:
    """Download audio, generate captions, and mux everything into a social-media MP4."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        audio_path = tmp / "audio.wav"
        srt_path = tmp / "captions.srt"

        _download(audio_url, audio_path)

        has_captions = _write_srt(script_text, tts_start, tts_duration, srt_path)

        if has_captions:
            # Escape colons in the path for ffmpeg's filter graph syntax.
            safe_srt = str(srt_path).replace("\\", "/").replace(":", "\\:")
            vf = (
                f"subtitles='{safe_srt}':force_style="
                "'FontName=Arial,FontSize=26,Bold=1,PrimaryColour=&H00ffffff,"
                "OutlineColour=&H00000000,Outline=2,Shadow=1,"
                "Alignment=2,MarginV=30,MarginL=40,MarginR=40,WrapStyle=1'"
            )
            video_codec = ["-vf", vf, "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p"]
        else:
            video_codec = ["-c:v", "copy"]

        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(video),
                "-i", str(audio_path),
                *video_codec,
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                "-movflags", "+faststart",
                str(output),
            ],
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg mux failed: {result.stderr.decode()[-300:]}")


def run(image_url: str, audio_outputs_path: Path = AUDIO_OUTPUTS_FILE) -> list:
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)

    if not audio_outputs_path.exists():
        sys.exit(f"Error: {audio_outputs_path} not found. Run generate_audio.py first.")

    audio_outputs = json.loads(audio_outputs_path.read_text())
    completed_audio = [
        r for r in audio_outputs
        if r.get("status") == "complete" and r.get("audio_url")
    ]

    if not completed_audio:
        sys.exit("Error: no completed audio outputs found in audio_outputs.json.")

    print(f"[video] {len(completed_audio)} audio version(s) to process.")
    print(f"[video] Generating Luma video clip from image…")
    clip_url = _generate_luma_clip(image_url)
    print(f"[video] Luma clip ready: {clip_url}")

    raw_clip = VIDEO_DIR / "raw_clip.mp4"
    _download(clip_url, raw_clip)
    print(f"[video] Downloaded raw clip → {raw_clip.name}")

    looped = VIDEO_DIR / "looped_30s.mp4"
    _loop_to_duration(raw_clip, looped, TARGET_DURATION)
    print(f"[video] Looped to {TARGET_DURATION}s → {looped.name}")

    results = []
    for audio in completed_audio:
        safe_name = (
            audio["location"]
            .replace(" ", "_")
            .replace("/", "-")
            .replace("\\", "-")
        )
        af_id = audio["audioform_id"]
        out_path = VIDEO_DIR / f"{safe_name}_{af_id}.mp4"

        print(f"[video] Muxing audio for {audio['location']}…")
        try:
            _combine(
                looped,
                audio["audio_url"],
                out_path,
                script_text=audio.get("script_text", ""),
                tts_start=audio.get("tts_start", 0.0),
                tts_duration=audio.get("tts_duration", 0.0),
            )
            print(f"[video] ✓ {out_path.name}")
            results.append({
                "location":     audio["location"],
                "audioform_id": af_id,
                "video_path":   str(out_path),
                "video_filename": out_path.name,
                "status":       "complete",
            })
        except Exception as exc:
            print(f"[video] ✗ {audio['location']}: {exc}")
            results.append({
                "location":     audio["location"],
                "audioform_id": af_id,
                "video_path":   "",
                "video_filename": "",
                "status":       "failed",
                "error":        str(exc),
            })

    out_json = Path(__file__).parent / "data" / "video_outputs.json"
    out_json.write_text(json.dumps(results, indent=2))
    complete = sum(1 for r in results if r["status"] == "complete")
    print(f"\n[video] {complete}/{len(results)} videos ready → {VIDEO_DIR}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image_url", help="URL of the source image (output of generate_image.py)")
    parser.add_argument(
        "--audio-file",
        type=Path,
        default=AUDIO_OUTPUTS_FILE,
        help="Path to audio_outputs.json (default: data/audio_outputs.json)",
    )
    args = parser.parse_args()
    run(args.image_url, args.audio_file)
