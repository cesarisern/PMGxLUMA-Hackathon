"""Feed 1 — brand_corpus from a brand URL (scrape) or a brand name (web search)."""

import os
import re
import random
import time

import httpx
from anthropic import Anthropic
from feeds import parse_json

SYSTEM = "Extract brand information from the provided content. Output only valid JSON. No commentary."

PROMPT = """Extract a brand corpus from this content.
Output a single JSON object with exactly these fields:
- brand_id: slugified name (string)
- brand_url: the brand's official URL if known, else "" (string)
- brand_name: full brand name (string)
- mission: mission statement (string)
- core_values: list of 4-6 values (list of strings)
- tone_of_voice: list of 3-5 descriptors (list of strings)
- target_audience: who the brand serves (string)
- required_messages: 2-4 messages the brand always communicates (list of strings)
- banned_terms: terms incompatible with brand values (list of strings)
- cta: primary call to action with URL (string)
- compliance: list of content rules (list of strings)"""


def _looks_like_url(value: str) -> bool:
    """True if the input is a URL or bare domain, False if it's a plain brand name."""
    value = value.strip()
    if value.startswith(("http://", "https://")):
        return True
    # bare domain: no spaces and a dot followed by a TLD-like suffix
    return " " not in value and bool(re.search(r"\.[a-z]{2,}$", value, re.IGNORECASE))


def _scrape_url(url: str) -> tuple[str, str]:
    """Returns (content, resolved_url)."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    print(f"[brand] Fetching {url} via Jina Reader...")
    jina_url = f"https://r.jina.ai/{url}"

    # Keep this retry scope narrow and local to the flaky Jina scrape call.
    max_attempts = 4
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = httpx.get(jina_url, timeout=30)
            if response.status_code in (403, 429) or response.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"Retryable status code: {response.status_code}",
                    request=response.request,
                    response=response,
                )
            response.raise_for_status()
            return response.text[:8000], url
        except (httpx.ProxyError, httpx.TimeoutException, httpx.HTTPStatusError, httpx.NetworkError) as exc:
            last_error = exc
            if attempt == max_attempts:
                break
            # Exponential backoff with slight jitter to avoid synchronized retries.
            sleep_seconds = (2 ** (attempt - 1)) + random.uniform(0, 0.35)
            print(f"[brand] Jina fetch attempt {attempt}/{max_attempts} failed ({exc}); retrying in {sleep_seconds:.2f}s")
            time.sleep(sleep_seconds)

    raise last_error if last_error else RuntimeError("Jina scrape failed unexpectedly")


def _search_name(name: str) -> tuple[str, str]:
    """Web-search a brand name. Returns (content, resolved_url='')."""
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
                        f"[brand] Search source returned {response.status_code}; retrying in {sleep_seconds:.2f}s "
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
                        f"[brand] Search source request failed ({exc}); retrying in {sleep_seconds:.2f}s "
                        f"(attempt {attempt + 2}/{retries})"
                    )
                    time.sleep(sleep_seconds)
                    continue
                raise

        if last_error:
            raise last_error
        raise RuntimeError("Search source request failed without explicit error")

    query = f"{name} brand official website mission values"
    jina_key = os.getenv("JINA_API_KEY")
    if jina_key:
        print(f"[brand] Searching Jina for brand '{name}'...")
        content = _get_text_with_retry(
            f"https://s.jina.ai/{query}",
            headers={"Accept": "text/plain", "Authorization": f"Bearer {jina_key}"},
        )
    else:
        print(f"[brand] No JINA_API_KEY — searching DuckDuckGo for brand '{name}'...")
        ddg = f"https://lite.duckduckgo.com/lite/?q={query.replace(' ', '+')}"
        content = _get_text_with_retry(f"https://r.jina.ai/{ddg}")
    return content[:8000], ""


def fetch(client: Anthropic, source: str) -> dict:
    """Build a brand corpus from either a brand URL or a brand name.

    `source` may be a URL ("https://...", "example.com") or a plain name
    ("US Youth Soccer"). URLs are scraped; names are web-searched.
    """
    if _looks_like_url(source):
        content, resolved_url = _scrape_url(source)
    else:
        content, resolved_url = _search_name(source)

    print("[brand] Extracting brand corpus via Anthropic...")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM,
        messages=[{"role": "user", "content": PROMPT + "\n\nContent:\n" + content}],
    )
    corpus = parse_json(response.content[0].text)
    # Prefer a scraped URL; otherwise keep whatever the model resolved.
    if resolved_url:
        corpus["brand_url"] = resolved_url
    corpus.setdefault("brand_url", "")
    print(f"[brand] Done — {corpus.get('brand_name')}")
    return corpus
