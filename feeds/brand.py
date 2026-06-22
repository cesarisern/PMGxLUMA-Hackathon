"""Feed 1 — brand_corpus via Jina Reader + Anthropic extraction."""

import httpx
from anthropic import Anthropic
from feeds import parse_json

SYSTEM = "Extract brand information from website content. Output only valid JSON. No commentary."

PROMPT = """Extract a brand corpus from this website content.
Output a single JSON object with exactly these fields:
- brand_id: slugified name (string)
- brand_url: the source URL (string)
- brand_name: full brand name (string)
- mission: mission statement (string)
- core_values: list of 4-6 values (list of strings)
- tone_of_voice: list of 3-5 descriptors (list of strings)
- target_audience: who the brand serves (string)
- required_messages: 2-4 messages the brand always communicates (list of strings)
- banned_terms: terms incompatible with brand values (list of strings)
- cta: primary call to action with URL (string)
- compliance: list of content rules (list of strings)

Website content:
{content}"""


def fetch(client: Anthropic, url: str) -> dict:
    print(f"[brand] Fetching {url} via Jina Reader...")
    raw = httpx.get(f"https://r.jina.ai/{url}", timeout=30).text

    print("[brand] Extracting brand corpus via Anthropic...")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM,
        messages=[{"role": "user", "content": PROMPT.format(content=raw[:8000])}],
    )
    corpus = parse_json(response.content[0].text)
    corpus["brand_url"] = url
    print(f"[brand] Done — {corpus.get('brand_name')}")
    return corpus
