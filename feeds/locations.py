"""Feed 4 — locations via Jina Reader + Anthropic extraction.

Scrapes the brand website for club/chapter/store/location data so the CTA
can be localized: "Find a club in [city/state]" instead of generic "near you".
"""

import json
import httpx
from anthropic import Anthropic

SYSTEM = "Extract location data from website content. Output only valid JSON. No commentary."

FIND_LOCATIONS_PAGE_PROMPT = """Given this brand website content, identify the URL of a page
that lists locations, clubs, chapters, stores, or local branches — anywhere a user could
find or join a local presence of this brand.

Output a single JSON object:
{{
  "locations_url": "<full URL or null if not found>",
  "locations_url_label": "<link text or page description, or null>"
}}

Brand: {brand_name}
Website content:
{content}"""

EXTRACT_LOCATIONS_PROMPT = """Extract all locations from this website content.
Locations can be states, cities, regions, clubs, or chapters.

Output a single JSON object:
{{
  "locations": [
    {{
      "name": "<location name>",
      "type": "<state | city | region | club | chapter>",
      "cta_suffix": "<short phrase for CTA, e.g. 'in California' or 'in Chicago'>",
      "url": "<direct URL for this location if available, else null>"
    }}
  ],
  "total": <integer>,
  "coverage": "<brief description of what's covered, e.g. 'all 50 US states'>"
}}

Website content:
{content}"""


def fetch(client: Anthropic, brand_url: str, brand_name: str) -> dict:
    print(f"[locations] Scraping {brand_url} for location data...")
    main_content = httpx.get(f"https://r.jina.ai/{brand_url}", timeout=30).text

    # Step 1 — find the dedicated locations/clubs page if one exists
    find_response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=256,
        system=SYSTEM,
        messages=[{
            "role": "user",
            "content": FIND_LOCATIONS_PAGE_PROMPT.format(
                brand_name=brand_name,
                content=main_content[:6000],
            ),
        }],
    )
    pointer = json.loads(find_response.content[0].text)
    locations_url = pointer.get("locations_url")

    # Step 2 — scrape the locations page if found, else use main page
    if locations_url:
        print(f"[locations] Found locations page: {locations_url}")
        content = httpx.get(f"https://r.jina.ai/{locations_url}", timeout=30).text
    else:
        print("[locations] No dedicated locations page found — extracting from main site")
        content = main_content

    # Step 3 — extract structured locations
    extract_response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=SYSTEM,
        messages=[{
            "role": "user",
            "content": EXTRACT_LOCATIONS_PROMPT.format(content=content[:8000]),
        }],
    )
    result = json.loads(extract_response.content[0].text)
    result["source_url"] = locations_url or brand_url

    total = result.get("total", len(result.get("locations", [])))
    print(f"[locations] Done — {total} locations found ({result.get('coverage', '')})")
    return result
