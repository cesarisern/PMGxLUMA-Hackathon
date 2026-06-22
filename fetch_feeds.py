"""
Fetch all 3 data feeds and save to data/.

Usage:
    python fetch_feeds.py              # fetch all 3 feeds fresh
    python fetch_feeds.py --cached     # load from data/ if files exist (demo fallback)

Outputs:
    data/brand_corpus.json
    data/campaign_context.json
    data/trend_signal.json
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

FILES = {
    "brand":   DATA_DIR / "brand_corpus.json",
    "context": DATA_DIR / "campaign_context.json",
    "trends":  DATA_DIR / "trend_signal.json",
}


def save(name: str, data: dict) -> None:
    path = FILES[name]
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"[saved] {path}")


def load_cached(name: str) -> dict | None:
    path = FILES[name]
    if path.exists():
        print(f"[cached] Loading {path}")
        return json.loads(path.read_text())
    return None


def run(cached: bool = False) -> dict:
    from anthropic import Anthropic
    from feeds import brand, context, trends

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("Error: ANTHROPIC_API_KEY not set. Copy .env.example → .env and add your key.")

    client = Anthropic(api_key=api_key)
    results = {}

    # Feed 1 — brand_corpus
    if cached and (data := load_cached("brand")):
        results["brand"] = data
    else:
        results["brand"] = brand.fetch(client)
        save("brand", results["brand"])

    # Feed 2 — campaign_context
    if cached and (data := load_cached("context")):
        results["context"] = data
    else:
        results["context"] = context.fetch(client)
        save("context", results["context"])

    # Feed 3 — trend_signal
    if cached and (data := load_cached("trends")):
        results["trends"] = data
    else:
        try:
            results["trends"] = trends.fetch()
            save("trends", results["trends"])
        except Exception as e:
            print(f"[trends] Warning: live fetch failed ({e})")
            if cached_data := load_cached("trends"):
                print("[trends] Falling back to cached data")
                results["trends"] = cached_data
            else:
                sys.exit("[trends] No cached fallback available. Run without --cached first.")

    print("\nAll feeds ready:")
    print(f"  brand_corpus     → {FILES['brand']}")
    print(f"  campaign_context → {FILES['context']}")
    print(f"  trend_signal     → {FILES['trends']}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cached",
        action="store_true",
        help="Load from data/ if files exist (use for demo fallback)",
    )
    args = parser.parse_args()
    run(cached=args.cached)
