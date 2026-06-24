"""Feed 2 — campaign_context via Jina Search + Anthropic synthesis."""

from datetime import datetime, timezone
import random
import time

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
- cta_context: context around the sign-up call to action (string)"""


def _get_text_with_retry(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    retries: int = 3,
    timeout: int = 30,
) -> str:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = httpx.get(url, headers=headers, timeout=timeout)
            if response.status_code == 200:
                return response.text

            if response.status_code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                sleep_seconds = (0.6 * (2**attempt)) + random.uniform(0.0, 0.25)
                print(
                    f"[context] Source returned {response.status_code}; retrying in {sleep_seconds:.2f}s "
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
                    f"[context] Source request failed ({exc}); retrying in {sleep_seconds:.2f}s "
                    f"(attempt {attempt + 2}/{retries})"
                )
                time.sleep(sleep_seconds)
                continue
            raise

    if last_error:
        raise last_error
    raise RuntimeError("Context source request failed without explicit error")


def fetch(client: Anthropic, query: str) -> dict:
    import os
    jina_key = os.getenv("JINA_API_KEY")

    if jina_key:
        print(f"[context] Searching Jina: '{query}'...")
        results = _get_text_with_retry(
            f"https://s.jina.ai/{query}",
            headers={"Accept": "text/plain", "Authorization": f"Bearer {jina_key}"},
        )
    else:
        print(f"[context] No JINA_API_KEY — searching via DuckDuckGo: '{query}'...")
        ddg_url = f"https://lite.duckduckgo.com/lite/?q={query.replace(' ', '+')}"
        results = _get_text_with_retry(f"https://r.jina.ai/{ddg_url}")

    print("[context] Synthesizing campaign context via Anthropic...")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM,
        messages=[{"role": "user", "content": PROMPT + "\n\nSearch results:\n" + results[:6000]}],
    )
    context = parse_json(response.content[0].text)
    context["query"] = query
    context["fetched_at"] = datetime.now(timezone.utc).isoformat()
    print(f"[context] Done — live moment: {context.get('live_moment', '')[:80]}...")
    return context
