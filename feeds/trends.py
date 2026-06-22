"""Feed 3 — trend_signal via pytrends (Google Trends)."""

from datetime import datetime, timezone


def fetch(keywords: list, geo: str = "US") -> dict:
    from pytrends.request import TrendReq

    print(f"[trends] Fetching Google Trends for: {keywords}...")
    pytrends = TrendReq(hl="en-US", tz=0)
    pytrends.build_payload(kw_list=keywords, timeframe="now 7-d", geo=geo)

    interest_df = pytrends.interest_over_time()
    related = pytrends.related_queries()

    if interest_df.empty:
        raise ValueError("pytrends returned empty dataframe — Google may be blocking requests")

    # Drop isPartial column if present
    if "isPartial" in interest_df.columns:
        interest_df = interest_df.drop(columns=["isPartial"])

    latest = interest_df.iloc[-1][keywords].to_dict()
    peak_kw = max(latest, key=latest.get)

    rising_queries = []
    if related.get(peak_kw) and related[peak_kw].get("rising") is not None:
        rising_queries = related[peak_kw]["rising"]["query"].head(3).tolist()

    signal = {
        "fetched_at":      datetime.now(timezone.utc).isoformat(),
        "geo":             geo,
        "timeframe":       "past 7 days",
        "keywords":        keywords,
        "interest_scores": {k: int(v) for k, v in latest.items()},
        "spike_detected":  int(latest[peak_kw]) > 70,
        "peak_keyword":    peak_kw,
        "rising_queries":  rising_queries,
        "trending_angle":  (
            f"'{peak_kw}' trending at {int(latest[peak_kw])}/100"
            + (f" — rising: {', '.join(rising_queries)}" if rising_queries else "")
        ),
    }

    print(f"[trends] Done — peak: '{peak_kw}' at {int(latest[peak_kw])}/100")
    return signal
