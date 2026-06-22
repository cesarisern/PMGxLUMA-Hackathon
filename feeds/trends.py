"""Feed 3 — trend_signal: website traffic (SimilarWeb) + search trends (Google Trends) in parallel."""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
- visit_change_pct: month-over-month change as a percentage e.g. 12.5 or -3.2, or null (float or null)
- avg_visit_duration: average visit duration e.g. "3:24", or null (string or null)
- bounce_rate: bounce rate as a percentage e.g. 45.2, or null (float or null)
- top_traffic_sources: list of top traffic source types e.g. ["direct", "search", "social"] (list)
- top_pages: list of up to 5 top pages or sections driving traffic (list of strings)
- signal: one sentence summarising the traffic trend (string)"""


def _extract_domain(url: str) -> str:
    parsed = urlparse(url)
    domain = parsed.netloc or parsed.path
    return domain.removeprefix("www.")


def _fetch_website_traffic(client: Anthropic, domain: str) -> dict:
    sw_url = f"https://www.similarweb.com/website/{domain}/"
    print(f"[trends] Fetching website traffic for {domain}...")
    try:
        content = httpx.get(f"https://r.jina.ai/{sw_url}", timeout=30).text
        if "monthly visits" not in content.lower() and "total visits" not in content.lower():
            return {"available": False, "reason": "no traffic data in SimilarWeb response"}
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system=SYSTEM,
            messages=[{"role": "user", "content": SIMILARWEB_PROMPT + "\n\nContent:\n" + content[:6000]}],
        )
        data = parse_json(response.content[0].text)
        data["available"] = True
        data["source"] = "similarweb"
        print(f"[trends] Website traffic done — {data.get('signal', '')[:80]}")
        return data
    except Exception as e:
        print(f"[trends] Website traffic unavailable ({e})")
        return {"available": False, "reason": str(e)}


def _fetch_search_trends(keywords: list, geo: str = "US", retries: int = 3) -> dict:
    from pytrends.request import TrendReq

    print(f"[trends] Fetching search trends for: {keywords}...")
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
                print(f"[trends] Search trends attempt {attempt} failed — retrying in {wait}s...")
                time.sleep(wait)
    else:
        print(f"[trends] Search trends unavailable ({last_error})")
        return {"available": False, "reason": str(last_error)}

    if interest_df.empty:
        return {"available": False, "reason": "empty dataframe"}

    if "isPartial" in interest_df.columns:
        interest_df = interest_df.drop(columns=["isPartial"])

    latest = interest_df.iloc[-1][keywords].to_dict()
    peak_kw = max(latest, key=latest.get)

    rising_queries = []
    if related.get(peak_kw) and related[peak_kw].get("rising") is not None:
        rising_queries = related[peak_kw]["rising"]["query"].head(3).tolist()

    print(f"[trends] Search trends done — peak: '{peak_kw}' at {int(latest[peak_kw])}/100")
    return {
        "available":       True,
        "source":          "google_trends",
        "geo":             geo,
        "timeframe":       "past 7 days",
        "keywords":        keywords,
        "interest_scores": {k: int(v) for k, v in latest.items()},
        "peak_keyword":    peak_kw,
        "rising_queries":  rising_queries,
        "signal":          (
            f"'{peak_kw}' trending at {int(latest[peak_kw])}/100"
            + (f" — rising: {', '.join(rising_queries)}" if rising_queries else "")
        ),
    }


def fetch(client: Anthropic, brand_url: str, keywords: list, geo: str = "US") -> dict:
    domain = _extract_domain(brand_url)

    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_traffic = pool.submit(_fetch_website_traffic, client, domain)
        fut_trends  = pool.submit(_fetch_search_trends, keywords, geo)
        website_traffic = fut_traffic.result()
        search_trends   = fut_trends.result()

    signals = [
        s for s in [
            website_traffic.get("signal") if website_traffic.get("available") else None,
            search_trends.get("signal")   if search_trends.get("available")   else None,
        ] if s
    ]

    return {
        "fetched_at":      datetime.now(timezone.utc).isoformat(),
        "website_traffic": website_traffic,
        "search_trends":   search_trends,
        "traffic_signal":  " | ".join(signals) if signals else "no signal data available",
    }
