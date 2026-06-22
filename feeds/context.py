"""Feed 2 — campaign_context via Jina Search + Anthropic synthesis."""

from datetime import datetime, timezone
import httpx
from anthropic import Anthropic
from feeds import parse_json

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


def fetch(client: Anthropic, query: str) -> dict:
    import os
    jina_key = os.getenv("JINA_API_KEY")

    if jina_key:
        print(f"[context] Searching Jina: '{query}'...")
        results = httpx.get(
            f"https://s.jina.ai/{query}",
            headers={"Accept": "text/plain", "Authorization": f"Bearer {jina_key}"},
            timeout=30,
        ).text
    else:
        print(f"[context] No JINA_API_KEY — searching via DuckDuckGo: '{query}'...")
        ddg_url = f"https://lite.duckduckgo.com/lite/?q={query.replace(' ', '+')}"
        results = httpx.get(f"https://r.jina.ai/{ddg_url}", timeout=30).text

    print("[context] Synthesizing campaign context via Anthropic...")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM,
        messages=[{"role": "user", "content": PROMPT.format(results=results[:6000])}],
    )
    context = parse_json(response.content[0].text)
    context["query"] = query
    context["fetched_at"] = datetime.now(timezone.utc).isoformat()
    print(f"[context] Done — live moment: {context.get('live_moment', '')[:80]}...")
    return context
