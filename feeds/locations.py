"""Feed 4 — locations via Jina Reader + Anthropic extraction.

Scrapes the brand website for club/chapter/store/location data so the CTA
can be localized: "Find a club in [city/state]" instead of generic "near you".
"""

import random
import time

import httpx
from anthropic import Anthropic
from feeds import parse_json

SYSTEM = "Extract location data from website content. Output only valid JSON. No commentary."

FIND_LOCATIONS_PAGE_PROMPT = """Given this brand website content, identify the URL of a page
that lists locations, clubs, chapters, stores, or local branches — anywhere a user could
find or join a local presence of this brand.

Output a single JSON object:
{
  "locations_url": "<full URL or null if not found>",
  "locations_url_label": "<link text or page description, or null>"
}"""

EXTRACT_LOCATIONS_PROMPT = """Extract up to 20 of the most prominent locations from this website content.
Locations can be states, cities, regions, clubs, or chapters.

Output a single JSON object:
{
  "locations": [
    {
      "name": "<location name>",
      "type": "<state | city | region | club | chapter>",
      "cta_suffix": "<short phrase for CTA, e.g. 'in California' or 'in Chicago'>",
      "url": "<direct URL for this location if available, else null>"
    }
  ],
  "total": <integer — total found on page, even if list is capped at 20>,
  "coverage": "<brief description, e.g. 'all 50 US states' or 'major US cities'>"
}"""


def _get_jina_text(target_url: str, retries: int = 3, timeout: int = 30) -> str:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = httpx.get(f"https://r.jina.ai/{target_url}", timeout=timeout)
            if response.status_code == 200:
                return response.text

            if response.status_code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                sleep_seconds = (0.6 * (2**attempt)) + random.uniform(0.0, 0.25)
                print(
                    f"[locations] Jina returned {response.status_code}; retrying in {sleep_seconds:.2f}s "
                    f"(attempt {attempt + 2}/{retries})"
                )
                time.sleep(sleep_seconds)
                continue

            response.raise_for_status()
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt < retries - 1:
                sleep_seconds = (0.6 * (2**attempt)) + random.uniform(0.0, 0.25)
                print(
                    f"[locations] Jina request failed ({exc}); retrying in {sleep_seconds:.2f}s "
                    f"(attempt {attempt + 2}/{retries})"
                )
                time.sleep(sleep_seconds)
                continue
            raise

    if last_error:
        raise last_error
    raise RuntimeError("Jina request failed without an explicit error")


def fetch(client: Anthropic, brand_url: str, brand_name: str) -> dict:
    print(f"[locations] Scraping {brand_url} for location data...")
    main_content = _get_jina_text(brand_url)

    # Step 1 — find the dedicated locations/clubs page if one exists
    find_response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=256,
        system=SYSTEM,
        messages=[{
            "role": "user",
            "content": (
                FIND_LOCATIONS_PAGE_PROMPT
                + f"\n\nBrand: {brand_name}\nWebsite content:\n"
                + main_content[:6000]
            ),
        }],
    )
    pointer = parse_json(find_response.content[0].text)
    locations_url = pointer.get("locations_url")

    # Step 2 — scrape the locations page if found, else use main page
    if locations_url:
        print(f"[locations] Found locations page: {locations_url}")
        try:
            content = _get_jina_text(locations_url)
        except Exception as e:
            print(f"[locations] Locations page fetch failed ({e}) — falling back to main page content")
            content = main_content
    else:
        print("[locations] No dedicated locations page found — extracting from main site")
        content = main_content

    # Step 3 — extract structured locations
    extract_response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM,
        messages=[{
            "role": "user",
            "content": EXTRACT_LOCATIONS_PROMPT + "\n\nWebsite content:\n" + content[:8000],
        }],
    )
    result = parse_json(extract_response.content[0].text)
    result["source_url"] = locations_url or brand_url

    total = result.get("total", len(result.get("locations", [])))
    print(f"[locations] Done — {total} locations found ({result.get('coverage', '')})")
    return result
