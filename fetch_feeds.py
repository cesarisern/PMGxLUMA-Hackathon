"""
Fetch all 3 data feeds and save to data/.

Usage:
    python fetch_feeds.py                         # interactive prompts
    python fetch_feeds.py --cached                # load from data/ (demo fallback)
    python fetch_feeds.py \\
        --brand-url https://www.example.com \\
        --campaign "campaign description" \\
        --keywords "keyword1,keyword2,keyword3"

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


def prompt(label: str, hint: str = "") -> str:
    hint_str = f" ({hint})" if hint else ""
    value = input(f"\n{label}{hint_str}\n> ").strip()
    if not value:
        sys.exit(f"Error: {label} is required.")
    return value


def collect_inputs(args: argparse.Namespace) -> tuple[str, str, list[str]]:
    print("\n=== Dynamic Voice API — feed configuration ===")

    brand_url = args.brand_url or prompt(
        "Brand URL",
        hint="e.g. https://www.example.com — leave blank to skip website scrape",
    )

    campaign = args.campaign or prompt(
        "Campaign description",
        hint="describe the campaign angle, moment, and audience in plain English",
    )

    if args.keywords:
        keywords = [k.strip() for k in args.keywords.split(",")]
    else:
        raw = input(
            f"\nTrend keywords (comma-separated, or press Enter to auto-derive from campaign)\n> "
        ).strip()
        keywords = [k.strip() for k in raw.split(",")] if raw else None

    return brand_url, campaign, keywords


def derive_keywords(client, campaign: str) -> list[str]:
    """Ask Claude to suggest 4 Google Trends keywords from the campaign description."""
    print("[trends] Deriving keywords from campaign description...")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=256,
        system="Output only valid JSON. No commentary.",
        messages=[{
            "role": "user",
            "content": (
                f"Given this campaign description: \"{campaign}\"\n"
                "Suggest 4 short Google Trends search keywords that would measure "
                "audience interest relevant to this campaign.\n"
                "Output a JSON array of 4 strings only."
            ),
        }],
    )
    return json.loads(response.content[0].text)


def run(cached: bool = False, args: argparse.Namespace = None) -> dict:
    from anthropic import Anthropic
    from feeds import brand, context, trends

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("Error: ANTHROPIC_API_KEY not set. Copy .env.example → .env and add your key.")

    client = Anthropic(api_key=api_key)

    if cached:
        results = {}
        for key in ("brand", "context", "trends"):
            data = load_cached(key)
            if not data:
                sys.exit(f"No cached {key} found. Run without --cached first to populate data/.")
            results[key] = data
        return results

    brand_url, campaign, keywords = collect_inputs(args)

    if keywords is None:
        keywords = derive_keywords(client, campaign)
        print(f"[trends] Using keywords: {keywords}")

    results = {}

    # Feed 1 — brand_corpus
    results["brand"] = brand.fetch(client, url=brand_url)
    save("brand", results["brand"])

    # Feed 2 — campaign_context
    results["context"] = context.fetch(client, query=campaign)
    save("context", results["context"])

    # Feed 3 — trend_signal
    try:
        results["trends"] = trends.fetch(keywords=keywords)
        save("trends", results["trends"])
    except Exception as e:
        print(f"[trends] Warning: live fetch failed ({e})")
        if cached_data := load_cached("trends"):
            print("[trends] Falling back to cached data")
            results["trends"] = cached_data
        else:
            sys.exit("[trends] No cached fallback. Run once without --cached to populate data/.")

    print("\nAll feeds ready:")
    print(f"  brand_corpus     → {FILES['brand']}")
    print(f"  campaign_context → {FILES['context']}")
    print(f"  trend_signal     → {FILES['trends']}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch all 3 data feeds.")
    parser.add_argument("--brand-url",  help="Brand website URL")
    parser.add_argument("--campaign",   help="Campaign description (plain English)")
    parser.add_argument("--keywords",   help="Trend keywords, comma-separated")
    parser.add_argument("--cached",     action="store_true", help="Load from data/ (demo fallback)")
    args = parser.parse_args()
    run(cached=args.cached, args=args)
