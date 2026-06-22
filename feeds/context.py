"""Feed 2 — campaign_context via Jina Search + Anthropic synthesis."""

import json
from datetime import datetime, timezone
import httpx
from anthropic import Anthropic

CAMPAIGN_QUERY = "World Cup 2026 inspiring girls youth soccer sign up"

SYSTEM = "Synthesize search results into a campaign context object. Output only valid JSON. No commentary."

PROMPT = """Synthesize these search results into a campaign context object.
Output a single JSON object with exactly these fields:
- query: the search query used (string)
- fetched_at: ISO 8601 timestamp (string)
- live_moment: what's happening right now that's culturally relevant (string)
- campaign_angle: the core campaign message angle (string)
- narrative_themes: 3 story angles the campaign can use (list of strings)
- inspiring_stories: 2 concrete real-world examples or stories (list of strings)
- cta_context: context around the sign-up call to action (string)

Search results:
{results}"""


def fetch(client: Anthropic, query: str = CAMPAIGN_QUERY) -> dict:
    print(f"[context] Searching Jina: '{query}'...")
    results = httpx.get(
        f"https://s.jina.ai/{query}",
        headers={"Accept": "text/plain"},
        timeout=30,
    ).text

    print("[context] Synthesizing campaign context via Anthropic...")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM,
        messages=[{"role": "user", "content": PROMPT.format(results=results[:6000])}],
    )
    context = json.loads(response.content[0].text)
    context["query"] = query
    context["fetched_at"] = datetime.now(timezone.utc).isoformat()
    print(f"[context] Done — live moment: {context.get('live_moment', '')[:80]}...")
    return context
