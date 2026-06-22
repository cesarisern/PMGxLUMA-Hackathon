"""Feed 3 — trend_signal: website traffic via SimilarWeb (primary) + Google Trends (fallback).

Primary: scrapes SimilarWeb via Jina Reader to get real click/traffic data for the brand URL.
Fallback: pytrends Google Trends if SimilarWeb data is unavailable.
"""

import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from anthropic import Anthropic
from feeds import parse_json

SYSTEM = "Extract website traffic data from the content. Output only valid JSON. No commentary."

SIMILARWEB_PROMPT = """Extract website traffic and engagement data from this SimilarWeb page.
Output a single JSON object with exactly these fields:
- domain: the website domain (string)
- monthly_visits: estimated monthly visits as a number, or null if not found (integer or null)
- visit_change_pct: month-over-month change as a percentage, e.g. 12.5 or -3.2, or null (float or null)
- avg_visit_duration: average visit duration e.g. "3:24", or null (string or null)
- bounce_rate: bounce rate as a percentage e.g. 45.2, or null (float or null)
- top_traffic_sources: list of top traffic source types e.g. ["direct", "search", "social"] (list)
- top_pages: list of up to 5 top pages or sections driving traffic (list of strings)
- traffic_signal: one sentence summarising the traffic trend (string)

Content:
{content}"""


def _extract_domain(url: str) -> str:
    parsed = urlparse(url)
    domain = parsed.netloc or parsed.path
    return domain.removeprefix("www.")


def _fetch_similarweb(client: Anthropic, domain: str) -> dict | None:
    sw_url = f"https://www.similarweb.com/website/{domain}/"
    print(f"[trends] Fetching SimilarWeb traffic data for {domain}...")
    try:
        content = httpx.get(f"https://r.jina.ai/{sw_url}", timeout=30).text
        if "monthly visits" not in content.lower() and "total visits" not in content.lower():
            print("[trends] SimilarWeb returned no traffic data — falling back to Google Trends")
            return None
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system=SYSTEM,
            messages=[{"role": "user", "content": SIMILARWEB_PROMPT.format(content=content[:6000])}],
        )
        data = parse_json(response.content[0].text)
        data["source"] = "similarweb"
        data["domain"] = domain
        return data
    except Exception as e:
        print(f"[trends] SimilarWeb fetch failed ({e}) — falling back to Google Trends")
        return None


def _fetch_google_trends(keywords: list, geo: str = "US", retries: int = 3) -> dict:
    from pytrends.request import TrendReq

    print(f"[trends] Fetching Google Trends for: {keywords}...")
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            pytrends = TrendReq(hl="en-US", tz=0)
            pytrends.build_payload(kw_list=keywords, timeframe="now 7-d", geo=geo)
            interest_df = pytrends.interest_over_time()
            related = pytrends.related_queries()
            break
        except Exception as e:
            last_error = e
            if attempt < retries:
                wait = attempt * 5
                print(f"[trends] Attempt {attempt} failed ({e}) — retrying in {wait}s...")
                time.sleep(wait)
    else:
        raise last_error

    if interest_df.empty:
        raise ValueError("pytrends returned empty dataframe")

    if "isPartial" in interest_df.columns:
        interest_df = interest_df.drop(columns=["isPartial"])

    latest = interest_df.iloc[-1][keywords].to_dict()
    peak_kw = max(latest, key=latest.get)

    rising_queries = []
    if related.get(peak_kw) and related[peak_kw].get("rising") is not None:
        rising_queries = related[peak_kw]["rising"]["query"].head(3).tolist()

    return {
        "source":          "google_trends",
        "geo":             geo,
        "timeframe":       "past 7 days",
        "keywords":        keywords,
        "interest_scores": {k: int(v) for k, v in latest.items()},
        "peak_keyword":    peak_kw,
        "rising_queries":  rising_queries,
        "traffic_signal":  (
            f"'{peak_kw}' trending at {int(latest[peak_kw])}/100"
            + (f" — rising: {', '.join(rising_queries)}" if rising_queries else "")
        ),
    }


def fetch(client: Anthropic, brand_url: str, keywords: list, geo: str = "US") -> dict:
    domain = _extract_domain(brand_url)
    now = datetime.now(timezone.utc).isoformat()

    sw_data = _fetch_similarweb(client, domain)

    if sw_data:
        print(f"[trends] Done — {sw_data.get('traffic_signal', '')}")
        sw_data["fetched_at"] = now
        return sw_data

    # Fallback to Google Trends
    gt_data = _fetch_google_trends(keywords, geo)
    gt_data["fetched_at"] = now
    spike = int(gt_data["interest_scores"].get(gt_data["peak_keyword"], 0)) > 70
    gt_data["spike_detected"] = spike
    print(f"[trends] Done — {gt_data['traffic_signal']}")
    return gt_data
