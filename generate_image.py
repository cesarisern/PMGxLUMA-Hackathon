import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from luma_agents import Luma

load_dotenv()

client = Luma()

DATA_FILE = Path(__file__).parent / "data" / "campaign_context.json"
BRAND_FILE = Path(__file__).parent / "data" / "brand_corpus.json"


def build_prompt(context: str | dict, brand_colours: list[str] | None = None) -> str:
    if isinstance(context, dict):
        parts = []
        if angle := context.get("campaign_angle"):
            parts.append(angle)
        if moment := context.get("live_moment"):
            parts.append(moment)
        if themes := context.get("narrative_themes"):
            parts.append(themes[0])
        if stories := context.get("inspiring_stories"):
            parts.append(stories[0])
        scene = ". ".join(parts)
    else:
        scene = context

    colour_hint = ""
    if brand_colours and len(brand_colours) >= 2:
        c1, c2 = brand_colours[0], brand_colours[1]
        colour_hint = (
            f"Subtle {c1} ambient light glow in the top-right corner and "
            f"{c2} ambient light glow in the bottom-left corner. "
        )
    elif brand_colours:
        colour_hint = f"Subtle {brand_colours[0]} ambient light glow on the corners. "

    return (
        f"A premium lifestyle photograph depicting a relevant scene for this ad campaign: {scene}. "
        "Tall portrait composition (9:16), subject and action fill the entire frame edge to edge. "
        "85mm portrait compression, wide aperture bokeh, subject in sharp focus. "
        f"Cinematic colour grade. {colour_hint}"
        "Natural directional sunlight, late afternoon. "
        "High contrast, photorealistic, premium lifestyle aesthetic. "
        "No visible brand logos, text, or markings on clothing or equipment. "
        "No photography equipment in the scene."
    )


cli_context = " ".join(sys.argv[1:]).strip() if len(sys.argv) > 1 else None

if cli_context:
    context_value = cli_context
elif DATA_FILE.exists():
    context_value = json.loads(DATA_FILE.read_text())
    print(f"[image] Loaded campaign context from {DATA_FILE}")
else:
    sys.exit(
        f"Error: no context provided. Pass a description as an argument or run "
        f"fetch_feeds.py first to generate {DATA_FILE}."
    )

brand_colours: list[str] = []
if BRAND_FILE.exists():
    try:
        corpus = json.loads(BRAND_FILE.read_text())
        dc = corpus.get("dominant_colours") or {}
        brand_colours = dc.get("logo_colours") or dc.get("web_colours") or []
    except Exception:
        pass

prompt_text = build_prompt(context_value, brand_colours)
print(f"[image] Prompt: {prompt_text}")

generation = client.generations.create(
    prompt=prompt_text,
    aspect_ratio="9:16",
)

while generation.state not in ("completed", "failed"):
    time.sleep(2)
    generation = client.generations.get(generation.id)

if generation.state == "completed":
    print(generation.output[0].url)
else:
    print(generation.failure_reason, generation.failure_code)
