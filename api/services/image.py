import sys
import time
from pathlib import Path
from typing import Any

import db
from services import brief as brief_service

ROOT_DIR = Path(__file__).resolve().parents[2]


def _build_prompt(context: dict, brand_colours: list[str] | None = None) -> str:
    parts = []
    if angle := context.get("campaign_angle"):
        parts.append(angle)
    if moment := context.get("live_moment"):
        parts.append(moment)
    if themes := context.get("narrative_themes"):
        parts.append(themes[0])
    if stories := context.get("inspiring_stories"):
        parts.append(stories[0])
    scene = ". ".join(parts) if parts else str(context)

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


def generate_image(run_id: int) -> dict[str, Any]:
    """Generate a Luma image for this run.

    Returns a dict with imageUrl, prompt, and the context data needed to
    generate clips in the next phase.
    """
    db.init()
    brand, context, _trends, _locations = brief_service.get_run_inputs(run_id)

    dc = brand.get("dominant_colours") or {}
    brand_colours = dc.get("web_colours") or []
    target_audience = brand.get("target_audience", "")

    prompt = _build_prompt(context, brand_colours)
    print(f"[image-service] Prompt: {prompt[:120]}...")

    from luma_agents import Luma
    client = Luma()
    generation = client.generations.create(prompt=prompt, aspect_ratio="9:16")

    while generation.state not in ("completed", "failed"):
        time.sleep(2)
        generation = client.generations.get(generation.id)

    if generation.state == "failed":
        raise RuntimeError(
            f"Luma image generation failed: {generation.failure_reason} ({generation.failure_code})"
        )

    image_url = generation.output[0].url
    print(f"[image-service] Image ready — {image_url}")
    return {
        "imageUrl": image_url,
        "prompt": prompt,
        "context": context,
        "brand_colours": brand_colours,
        "target_audience": target_audience,
    }


def generate_clips(
    image_url: str,
    context: dict,
    brand_colours: list[str],
    target_audience: str = "",
) -> list[str]:
    """Generate Luma video clips from the image URL. Returns a list of clip URLs."""
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))
    import generate_video_from_image
    return generate_video_from_image.generate_clips(image_url, context, brand_colours, target_audience)
