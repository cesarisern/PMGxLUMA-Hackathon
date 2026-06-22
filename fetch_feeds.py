"""
Fetch all 4 data feeds and save to data/.

Usage:
    python fetch_feeds.py                         # interactive prompts
    python fetch_feeds.py --cached                # load from data/ (demo fallback)
    python fetch_feeds.py \\
        --brand-url https://www.example.com \\
        --campaign "campaign description"

Outputs:
    data/brand_corpus.json
    data/campaign_context.json
    data/trend_signal.json
    data/locations.json
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
    "brand":     DATA_DIR / "brand_corpus.json",
    "context":   DATA_DIR / "campaign_context.json",
    "trends":    DATA_DIR / "trend_signal.json",
    "locations": DATA_DIR / "locations.json",
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


def collect_inputs(args: argparse.Namespace) -> tuple[str, str]:
    print("\n=== Dynamic Voice API — feed configuration ===")

    brand_url = args.brand_url or prompt(
        "Brand URL",
        hint="e.g. https://www.example.com",
    )

    campaign = args.campaign or prompt(
        "Campaign description",
        hint="describe the campaign angle, moment, and audience in plain English",
    )

    return brand_url, campaign


def derive_keywords(client, brand_corpus: dict, campaign: str) -> list[str]:
    """Derive 4 Google Trends keywords from the brand corpus + campaign description."""
    print("[trends] Deriving keywords from brand and campaign...")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=256,
        system="Output only valid JSON. No commentary.",
        messages=[{
            "role": "user",
            "content": (
                f"Brand: {brand_corpus.get('brand_name')}\n"
                f"Target audience: {brand_corpus.get('target_audience')}\n"
                f"Core values: {brand_corpus.get('core_values')}\n"
                f"Campaign: {campaign}\n\n"
                "Suggest 4 short Google Trends search keywords that would measure "
                "audience interest relevant to this brand and campaign. "
                "Keywords should be what this audience actually searches for.\n"
                "Output a JSON array of 4 strings only."
            ),
        }],
    )
    from feeds import parse_json
    keywords = parse_json(response.content[0].text)
    print(f"[trends] Keywords: {keywords}")
    return keywords


def run(cached: bool = False, args: argparse.Namespace = None) -> dict:
    import db
    from anthropic import Anthropic
    from feeds import brand, context, trends, locations

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("Error: ANTHROPIC_API_KEY not set. Copy .env.example → .env and add your key.")

    db.init()
    client = Anthropic(api_key=api_key)

    if cached:
        results = {}
        for key in ("brand", "context", "trends", "locations"):
            data = load_cached(key)
            if not data:
                sys.exit(f"No cached {key} found. Run without --cached first to populate data/.")
            results[key] = data
        return results

    brand_url, campaign = collect_inputs(args)
    results = {}

    run_id = db.create_run(brand_url, campaign)
    print(f"[db] Run #{run_id} created")

    # Feed 1 — brand_corpus
    results["brand"] = brand.fetch(client, url=brand_url)
    save("brand", results["brand"])
    db.save_brand(run_id, results["brand"])

    # Feed 2 — campaign_context
    results["context"] = context.fetch(client, query=campaign)
    save("context", results["context"])
    db.save_context(run_id, results["context"])

    # Feed 3 — trend_signal (keywords derived from brand + campaign)
    keywords = derive_keywords(client, results["brand"], campaign)
    try:
        results["trends"] = trends.fetch(keywords=keywords)
        save("trends", results["trends"])
        db.save_trends(run_id, results["trends"])
    except Exception as e:
        print(f"[trends] Warning: live fetch failed ({e})")
        if cached_data := load_cached("trends"):
            print("[trends] Falling back to cached data")
            results["trends"] = cached_data
            db.save_trends(run_id, results["trends"])
        else:
            sys.exit("[trends] No cached fallback. Run once without --cached to populate data/.")

    # Feed 4 — locations (scraped from brand website)
    results["locations"] = locations.fetch(
        client,
        brand_url=brand_url,
        brand_name=results["brand"].get("brand_name", ""),
    )
    save("locations", results["locations"])
    db.save_locations(run_id, results["locations"])

    print("\nAll feeds ready:")
    print(f"  brand_corpus     → {FILES['brand']}")
    print(f"  campaign_context → {FILES['context']}")
    print(f"  trend_signal     → {FILES['trends']}")
    print(f"  locations        → {FILES['locations']}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch all 3 data feeds.")
    parser.add_argument("--brand-url", help="Brand website URL")
    parser.add_argument("--campaign",  help="Campaign description (plain English)")
    parser.add_argument("--cached",    action="store_true", help="Load from data/ (demo fallback)")
    args = parser.parse_args()
    run(cached=args.cached, args=args)
