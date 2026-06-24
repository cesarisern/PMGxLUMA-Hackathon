"""
Generate polished social-media MP4 videos from a Luma image URL + Audiostack audio outputs.

Video structure (30 s total):
  1. Static image hold          3 s
  2. Montage: 5 × 5 s Luma clips, 4 × 0.5 s xfade transitions   23 s
  3. Brand colour gradient end card with logo                      5 s
  (two 0.5 s transitions between segments account for the final total)

One master visual track is assembled; each audio version is muxed against that
same master with its own timed caption track burned in.

Luma prompts are derived from campaign_context.json and brand_corpus.json so
the generated motion reflects the campaign theme and brand palette.

Usage:
    python generate_video_from_image.py <image_url> [--brand-url https://nike.com]
    python generate_video_from_image.py <image_url> --audio-file path/to/audio_outputs.json
"""

import argparse
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv
from luma_agents import Luma

load_dotenv()

client = Luma()

AUDIO_OUTPUTS_FILE = Path(__file__).parent / "data" / "audio_outputs.json"
BRAND_CORPUS_FILE  = Path(__file__).parent / "data" / "brand_corpus.json"
CAMPAIGN_CTX_FILE  = Path(__file__).parent / "data" / "campaign_context.json"
VIDEO_DIR  = Path(__file__).parent / "data" / "videos"
FONTS_DIR  = Path(__file__).parent / "fonts"
FONT_PATH  = FONTS_DIR / "BebasNeue-Regular.ttf"
FONT_URL   = "https://raw.githubusercontent.com/google/fonts/main/ofl/bebasneue/BebasNeue-Regular.ttf"

N_CLIPS        = 5
CLIP_DURATION  = 5        # seconds — Luma limit for start_frame mode
TRANSITION_DUR = 0.5      # xfade crossfade duration
STATIC_DUR     = 3        # opening still-image hold
MONTAGE_DUR    = N_CLIPS * CLIP_DURATION - (N_CLIPS - 1) * TRANSITION_DUR  # 23 s
END_CARD_DUR   = 5        # brand colour gradient end card
# Total: 3 + 23 − 0.5 + 5 − 0.5 = 30.0 s


# ---------------------------------------------------------------------------
# Font
# ---------------------------------------------------------------------------

def _ensure_font() -> Path | None:
    if FONT_PATH.exists():
        return FONT_PATH
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        print("[video] Downloading Montserrat Bold…")
        urllib.request.urlretrieve(FONT_URL, str(FONT_PATH))
        return FONT_PATH
    except Exception as exc:
        print(f"[video] Font download failed, falling back to Arial: {exc}")
        return None


# ---------------------------------------------------------------------------
# Logo
# ---------------------------------------------------------------------------

def _scrape_brand_logo(brand_url: str) -> bytes | None:
    if not brand_url:
        return None
    try:
        from feeds.colours import scrape_logo
        logo_bytes = scrape_logo(brand_url)
        if logo_bytes:
            print("[video] Brand logo scraped from homepage")
        return logo_bytes
    except Exception as exc:
        print(f"[video] Logo scrape failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# ffmpeg helpers
# ---------------------------------------------------------------------------

def _download(url: str, dest: Path) -> None:
    urllib.request.urlretrieve(url, str(dest))


def _run_ff(*args: str) -> None:
    result = subprocess.run(["ffmpeg", "-y", *args], capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error:\n{result.stderr.decode()[-500:]}")


def _video_size(path: Path) -> tuple[int, int]:
    r = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=s=x:p=0", str(path),
        ],
        capture_output=True, text=True,
    )
    w, h = r.stdout.strip().split("x")
    return int(w), int(h)


# ---------------------------------------------------------------------------
# SRT caption generation
# ---------------------------------------------------------------------------

def _fmt_srt_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t % 1) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _write_srt(script_text: str, tts_start: float, tts_duration: float, srt_path: Path) -> bool:
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


# ---------------------------------------------------------------------------
# Luma clip generation
# ---------------------------------------------------------------------------

def _build_luma_prompts(context: dict, brand_colours: list[str], target_audience: str = "") -> list[str]:
    angle  = context.get("campaign_angle", "")
    moment = context.get("live_moment", "")
    themes = context.get("narrative_themes") or []
    theme  = themes[0] if themes else angle

    colour_suffix = ""
    if brand_colours:
        cols = " and ".join(brand_colours[:2])
        colour_suffix = f" {cols} tonal warmth in the ambient light."

    campaign_note = angle or moment or ""
    # Describe a person or group that matches the campaign's target without being prescriptive
    audience_note = f", {target_audience}" if target_audience else ""

    # Five compositions: solo close-up, small group, solo wide, crowd, pair — each
    # explicitly diverse so Luma generates varied subject counts across the clips.
    return [
        (
            f"One person{audience_note}, close-up, intimate depth-of-field shift. "
            f"Slow cinematic push in. {campaign_note}.{colour_suffix} "
            "Diverse, authentic, photorealistic. Premium lifestyle aesthetic."
        ),
        (
            f"Small diverse group of 3-4 people{audience_note} together, energetic. "
            f"Gentle horizontal drift, sweeping atmospheric parallax. {theme}.{colour_suffix} "
            "Multicultural cast, authentic, photorealistic. Premium lifestyle aesthetic."
        ),
        (
            f"One person{audience_note}, full-body wide shot, confident and dynamic. "
            f"Rising reveal, subtle upward arc. {campaign_note}.{colour_suffix} "
            "Diverse, authentic, photorealistic. Premium lifestyle aesthetic."
        ),
        (
            f"Crowd of diverse people{audience_note}, community gathering, vibrant atmosphere. "
            f"Soft parallax depth, layered dimensionality. {theme}.{colour_suffix} "
            "Multicultural, authentic, photorealistic. Premium lifestyle aesthetic."
        ),
        (
            f"Two people{audience_note}, side by side, connection and shared energy. "
            f"Slow orbit, dynamic cinematic movement. {moment or theme}.{colour_suffix} "
            "Diverse duo, authentic, photorealistic. Premium lifestyle aesthetic."
        ),
    ]


def _generate_luma_clips(image_url: str, prompts: list[str]) -> list[str]:
    def _one(prompt: str, idx: int) -> str:
        generation = client.generations.create(
            prompt=prompt,
            type="video",
            model="ray-3.2",
            aspect_ratio="9:16",
            video={"start_frame": {"url": image_url}, "loop": True, "duration": "5s"},
        )
        print(f"[video] Clip {idx} submitted: {generation.id}")
        while generation.state not in ("completed", "failed"):
            time.sleep(5)
            generation = client.generations.get(generation.id)
            print(f"[video] Clip {idx} state: {generation.state}")
        if generation.state != "completed":
            raise RuntimeError(
                f"Clip {idx} failed: {generation.failure_reason} ({generation.failure_code})"
            )
        return generation.output[0].url

    results: list[str | None] = [None] * len(prompts)
    with ThreadPoolExecutor(max_workers=len(prompts)) as exe:
        futures = {exe.submit(_one, p, i): i for i, p in enumerate(prompts)}
        for fut in as_completed(futures):
            results[futures[fut]] = fut.result()
    return results


# ---------------------------------------------------------------------------
# Public helper — generate clips without assembling (for parallel pre-generation)
# ---------------------------------------------------------------------------

def generate_clips(
    image_url: str,
    campaign_ctx: dict,
    brand_colours: list[str],
    target_audience: str = "",
) -> list[str]:
    """Generate Luma clips and return their URLs, without downloading or assembling.

    Call this before run() to pre-generate clips while audio is being produced.
    Pass the returned URLs as pregenerated_clip_urls to run() to skip re-generation.
    """
    prompts = _build_luma_prompts(campaign_ctx, brand_colours, target_audience)
    print(f"[video] Pre-generating {N_CLIPS} Luma clips in parallel…")
    return _generate_luma_clips(image_url, prompts)


# ---------------------------------------------------------------------------
# Video assembly stages
# ---------------------------------------------------------------------------

def _make_static_hold(image_url: str, duration: int, dest: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        img_path = Path(tmp) / "frame.jpg"
        _download(image_url, img_path)
        _run_ff(
            "-loop", "1", "-r", "24", "-i", str(img_path),
            "-t", str(duration),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "23",
            str(dest),
        )


def _stitch_montage(clips: list[Path], dest: Path) -> None:
    n = len(clips)
    fc_parts = []
    for i in range(1, n):
        in0 = "[0:v]" if i == 1 else f"[v{i-1}]"
        out = "[vout]" if i == n - 1 else f"[v{i}]"
        offset = i * (CLIP_DURATION - TRANSITION_DUR)
        fc_parts.append(
            f"{in0}[{i}:v]xfade=transition=fade:duration={TRANSITION_DUR}:offset={offset}{out}"
        )
    inputs = [arg for clip in clips for arg in ("-i", str(clip))]
    _run_ff(
        *inputs,
        "-filter_complex", ";".join(fc_parts),
        "-map", "[vout]", "-an",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "23",
        str(dest),
    )


def _make_end_card(colours: list[str], logo_bytes: bytes | None, duration: int, dest: Path, w: int, h: int) -> None:
    from PIL import Image

    if not colours:
        colours = ["#0d0d0d", "#1a1a2e"]

    rgbs = []
    for c in colours[:4]:
        c = c.lstrip("#")
        if len(c) == 3:
            c = c[0] * 2 + c[1] * 2 + c[2] * 2
        rgbs.append((int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)))

    n = len(rgbs)
    row_data = bytearray()
    for y in range(h):
        t = y / (h - 1) if h > 1 else 0.0
        seg = t * (n - 1)
        i = min(int(seg), n - 2)
        lt = seg - i
        r0, g0, b0 = rgbs[i]
        r1, g1, b1 = rgbs[i + 1]
        row_data += bytes([
            min(255, max(0, int(r0 + (r1 - r0) * lt))),
            min(255, max(0, int(g0 + (g1 - g0) * lt))),
            min(255, max(0, int(b0 + (b1 - b0) * lt))),
        ])

    img = Image.frombytes("RGB", (1, h), bytes(row_data)).resize((w, h), Image.NEAREST)

    if logo_bytes:
        try:
            logo = Image.open(io.BytesIO(logo_bytes))
            if logo.mode == "P":
                logo = logo.convert("RGBA")
            if logo.mode != "RGBA":
                logo = logo.convert("RGBA")
            max_w, max_h = w // 3, h // 8
            logo.thumbnail((max_w, max_h), Image.LANCZOS)
            x = (w - logo.width) // 2
            y = (h - logo.height) // 2
            img_rgba = img.convert("RGBA")
            img_rgba.paste(logo, (x, y), logo)
            img = img_rgba.convert("RGB")
        except Exception as exc:
            print(f"[video] Logo overlay failed, skipping: {exc}")

    with tempfile.TemporaryDirectory() as tmp:
        card_png = Path(tmp) / "end_card.png"
        img.save(str(card_png))
        _run_ff(
            "-loop", "1", "-r", "24", "-i", str(card_png),
            "-t", str(duration),
            "-vf", "fade=t=in:st=0:d=0.5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "23",
            str(dest),
        )


def _assemble_master(static: Path, montage: Path, end_card: Path, dest: Path) -> None:
    # static(3s) → montage(23s) → end_card(5s) with 0.5s xfades = 30.0 s
    s2m_offset = STATIC_DUR - TRANSITION_DUR               # 2.5
    m2e_offset = s2m_offset + MONTAGE_DUR - TRANSITION_DUR  # 25.0
    fc = (
        f"[0:v][1:v]xfade=transition=fade:duration={TRANSITION_DUR}:offset={s2m_offset}[v01];"
        f"[v01][2:v]xfade=transition=fade:duration={TRANSITION_DUR}:offset={m2e_offset}[vout]"
    )
    _run_ff(
        "-i", str(static), "-i", str(montage), "-i", str(end_card),
        "-filter_complex", fc,
        "-map", "[vout]", "-an",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "23",
        str(dest),
    )


# ---------------------------------------------------------------------------
# Mux audio + captions into master
# ---------------------------------------------------------------------------

def _combine(
    video: Path,
    audio_url: str,
    output: Path,
    script_text: str = "",
    tts_start: float = 0.0,
    tts_duration: float = 0.0,
    font_path: Path | None = None,
    h: int = 0,
) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        audio_path = tmp / "audio.wav"
        srt_path   = tmp / "captions.srt"

        _download(audio_url, audio_path)
        has_captions = _write_srt(script_text, tts_start, tts_duration, srt_path)

        if has_captions:
            safe_srt = str(srt_path).replace("\\", "/").replace(":", "\\:")
            font_name = "Bebas Neue" if font_path else "Arial"
            fontsdir_opt = ""
            if font_path:
                safe_fd = str(FONTS_DIR).replace("\\", "/").replace(":", "\\:")
                fontsdir_opt = f":fontsdir='{safe_fd}'"
            # Position text in the bottom 50%: MarginV = 25% of video height from the
            # bottom edge (Alignment=2 measures from bottom). Falls back to a sensible
            # pixel value if height is unknown.
            margin_v = max(60, h // 4) if h else 320
            vf = (
                f"subtitles='{safe_srt}'{fontsdir_opt}:force_style="
                f"'FontName={font_name},FontSize=18,Bold=0,PrimaryColour=&H00ffffff,"
                f"OutlineColour=&H00000000,Outline=2,Shadow=1,"
                f"Alignment=2,MarginV={margin_v},MarginL=40,MarginR=40,WrapStyle=1'"
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
                "-c:a", "aac", "-b:a", "192k",
                "-shortest", "-movflags", "+faststart",
                str(output),
            ],
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg mux failed: {result.stderr.decode()[-300:]}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(
    image_url: str,
    audio_outputs_path: Path = AUDIO_OUTPUTS_FILE,
    brand_url: str = "",
    pregenerated_clip_urls: list[str] | None = None,
) -> list:
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)

    if not audio_outputs_path.exists():
        sys.exit(f"Error: {audio_outputs_path} not found. Run generate_audio.py first.")

    audio_outputs = json.loads(audio_outputs_path.read_text())
    completed_audio = [r for r in audio_outputs if r.get("status") == "complete" and r.get("audio_url")]
    if not completed_audio:
        sys.exit("Error: no completed audio outputs found in audio_outputs.json.")

    brand_corpus = json.loads(BRAND_CORPUS_FILE.read_text()) if BRAND_CORPUS_FILE.exists() else {}
    campaign_ctx = json.loads(CAMPAIGN_CTX_FILE.read_text()) if CAMPAIGN_CTX_FILE.exists() else {}

    effective_brand_url = brand_url or brand_corpus.get("brand_url", "")
    dc = brand_corpus.get("dominant_colours") or {}
    brand_colours    = dc.get("logo_colours") or dc.get("web_colours") or []
    target_audience  = brand_corpus.get("target_audience", "")

    print(f"[video] {len(completed_audio)} audio version(s) to process.")

    font_path  = _ensure_font()
    logo_bytes = _scrape_brand_logo(effective_brand_url)

    if pregenerated_clip_urls:
        clip_urls = pregenerated_clip_urls
        print(f"[video] Using {len(clip_urls)} pre-generated Luma clip URLs.")
    else:
        prompts = _build_luma_prompts(campaign_ctx, brand_colours, target_audience)
        print(f"[video] Generating {N_CLIPS} Luma clips in parallel…")
        clip_urls = _generate_luma_clips(image_url, prompts)

    raw_clips: list[Path] = []
    for i, url in enumerate(clip_urls):
        p = VIDEO_DIR / f"raw_clip_{i}.mp4"
        _download(url, p)
        print(f"[video] Downloaded clip {i} → {p.name}")
        raw_clips.append(p)

    static = VIDEO_DIR / "static.mp4"
    print("[video] Creating static image hold…")
    _make_static_hold(image_url, STATIC_DUR, static)

    montage = VIDEO_DIR / "montage.mp4"
    print("[video] Stitching montage with crossfades…")
    _stitch_montage(raw_clips, montage)

    w, h = _video_size(montage)

    end_card = VIDEO_DIR / "end_card.mp4"
    print("[video] Creating brand colour end card…")
    _make_end_card(brand_colours, logo_bytes, END_CARD_DUR, end_card, w, h)

    master = VIDEO_DIR / "master.mp4"
    print("[video] Assembling 30 s master…")
    _assemble_master(static, montage, end_card, master)

    results = []
    for audio in completed_audio:
        safe_name = (
            audio["location"]
            .replace(" ", "_")
            .replace("/", "-")
            .replace("\\", "-")
        )
        af_id    = audio["audioform_id"]
        out_path = VIDEO_DIR / f"{safe_name}_{af_id}.mp4"

        print(f"[video] Muxing audio for {audio['location']}…")
        try:
            _combine(
                master,
                audio["audio_url"],
                out_path,
                script_text=audio.get("script_text", ""),
                tts_start=audio.get("tts_start", 0.0),
                tts_duration=audio.get("tts_duration", 0.0),
                font_path=font_path,
                h=h,
            )
            print(f"[video] ✓ {out_path.name}")
            results.append({
                "location":       audio["location"],
                "audioform_id":   af_id,
                "video_path":     str(out_path),
                "video_filename": out_path.name,
                "status":         "complete",
            })
        except Exception as exc:
            print(f"[video] ✗ {audio['location']}: {exc}")
            results.append({
                "location":       audio["location"],
                "audioform_id":   af_id,
                "video_path":     "",
                "video_filename": "",
                "status":         "failed",
                "error":          str(exc),
            })

    out_json = Path(__file__).parent / "data" / "video_outputs.json"
    out_json.write_text(json.dumps(results, indent=2))
    complete = sum(1 for r in results if r["status"] == "complete")
    print(f"\n[video] {complete}/{len(results)} videos ready → {VIDEO_DIR}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image_url", help="URL of the source image (output of generate_image.py)")
    parser.add_argument("--brand-url", default="", help="Brand website URL (e.g. https://nike.com)")
    parser.add_argument(
        "--audio-file",
        type=Path,
        default=AUDIO_OUTPUTS_FILE,
        help="Path to audio_outputs.json (default: data/audio_outputs.json)",
    )
    args = parser.parse_args()
    run(args.image_url, args.audio_file, args.brand_url)
