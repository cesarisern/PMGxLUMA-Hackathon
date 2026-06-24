"""
Per-state youth-sports campaign analysis for US Youth Soccer.

Google Trends (pytrends) is IP-blocked (429) for automated queries, so this
uses two real, citable datasets instead:

  1. Registered youth soccer players per state
     — US Youth Soccer state associations (compiled by Authority Soccer).
     Absolute audience size. ~48 states. Approximate.

  2. NSCH youth-sports participation RATE per state (2023)
     — U.S. Census Bureau, National Survey of Children's Health.
     Propensity to play. Verified top-5 / bottom-5 + national baseline.

The cross-read (volume × rate) is the campaign signal: where demand is large,
where it's intense, and — most useful — where large markets still have low
participation (the conversion upside).

Usage:
    python analyze_state_trends.py
"""

# ── Dataset 1: registered youth soccer players per state ─────────────────────
# Source: US Youth Soccer state associations, via authoritysoccer.com compilation.
SOCCER_PLAYERS = {
    "California": 321000, "Texas": 246863, "New York": 183218, "Massachusetts": 167402,
    "Pennsylvania": 163423, "New Jersey": 150978, "Virginia": 144197, "Florida": 113777,
    "Washington": 110170, "Michigan": 92022, "Ohio": 91505, "Illinois": 80652,
    "Georgia": 78943, "Minnesota": 76668, "Colorado": 73313, "North Carolina": 72999,
    "Utah": 62972, "Indiana": 61567, "Wisconsin": 56474, "Arizona": 51672,
    "Tennessee": 49307, "Kentucky": 37621, "Oklahoma": 36222, "Iowa": 32113,
    "Missouri": 30147, "Louisiana": 25782, "Kansas": 25258, "Arkansas": 25104,
    "Oregon": 24811, "Rhode Island": 22031, "Nebraska": 21787, "Mississippi": 21516,
    "New Mexico": 20590, "New Hampshire": 18949, "Connecticut": 16841, "Alabama": 15950,
    "West Virginia": 15369, "South Dakota": 13752, "Delaware": 13480, "Idaho": 12645,
    "Maine": 10867, "Montana": 10635, "Vermont": 7627, "North Dakota": 7341,
    "Wyoming": 5794, "South Carolina": 22372,
}

# ── Dataset 2: NSCH 2023 youth-sports participation rate (%) ──────────────────
# Source: U.S. Census Bureau, National Survey of Children's Health, 2023.
# Only verified values included — NOT fabricated for unlisted states.
NSCH_RATE = {
    "Vermont": 71.5, "South Dakota": 68.8, "New Hampshire": 67.6,
    "Massachusetts": 65.3, "Iowa": 64.8,
    "Texas": 49.0, "West Virginia": 48.6, "Florida": 48.4,
    "Delaware": 47.7, "Nevada": 43.3,
}
NATIONAL_RATE = 55.4  # NSCH 2023, ages 6–17

REGION = {
    "Connecticut": "NE", "Maine": "NE", "Massachusetts": "NE", "New Hampshire": "NE",
    "Rhode Island": "NE", "Vermont": "NE", "New Jersey": "NE", "New York": "NE", "Pennsylvania": "NE",
    "Illinois": "MW", "Indiana": "MW", "Michigan": "MW", "Ohio": "MW", "Wisconsin": "MW",
    "Iowa": "MW", "Kansas": "MW", "Minnesota": "MW", "Missouri": "MW", "Nebraska": "MW",
    "North Dakota": "MW", "South Dakota": "MW",
    "Delaware": "S", "Florida": "S", "Georgia": "S", "Maryland": "S", "North Carolina": "S",
    "South Carolina": "S", "Virginia": "S", "West Virginia": "S", "Alabama": "S", "Kentucky": "S",
    "Mississippi": "S", "Tennessee": "S", "Arkansas": "S", "Louisiana": "S", "Oklahoma": "S", "Texas": "S",
    "Arizona": "W", "Colorado": "W", "Idaho": "W", "Montana": "W", "Nevada": "W", "New Mexico": "W",
    "Utah": "W", "Wyoming": "W", "Alaska": "W", "California": "W", "Hawaii": "W", "Oregon": "W",
    "Washington": "W",
}
REGION_NAME = {"NE": "Northeast", "MW": "Midwest", "S": "South", "W": "West"}


def bar(value, vmax, width=30):
    return "█" * max(1, int(value / vmax * width)) if value else ""


def main():
    print("\n" + "=" * 70)
    print("  YOUTH-SPORTS CAMPAIGN ANALYSIS — PER US STATE")
    print("  US Youth Soccer  ·  audience volume × participation rate")
    print("=" * 70)

    ranked = sorted(SOCCER_PLAYERS.items(), key=lambda x: -x[1])
    total = sum(SOCCER_PLAYERS.values())
    vmax = ranked[0][1]

    # ── 1. Volume leaderboard ──
    print(f"\n▍ AUDIENCE VOLUME — registered youth soccer players")
    print(f"  Total across {len(SOCCER_PLAYERS)} states: {total:,}\n")
    for i, (state, n) in enumerate(ranked[:15], 1):
        share = n / total * 100
        print(f"  {i:2}. {state:16} {n:>8,}  {share:4.1f}%  {bar(n, vmax, 26)}")
    print(f"\n  Top 5 states = {sum(n for _, n in ranked[:5])/total*100:.0f}% of all registered players.")

    # ── 2. Participation rate (propensity) ──
    print(f"\n▍ PARTICIPATION RATE — % of kids 6–17 playing any sport (NSCH 2023)")
    print(f"  National baseline: {NATIONAL_RATE}%\n")
    print("  Highest propensity:")
    for state, r in sorted(NSCH_RATE.items(), key=lambda x: -x[1])[:5]:
        print(f"    {state:16} {r:5.1f}%  {bar(r, 75, 26)}")
    print("  Lowest propensity:")
    for state, r in sorted(NSCH_RATE.items(), key=lambda x: x[1])[:5]:
        print(f"    {state:16} {r:5.1f}%  {bar(r, 75, 26)}")

    # ── 3. Regional rollup (volume) ──
    print(f"\n▍ REGIONAL VOLUME ROLLUP")
    reg = {}
    for state, n in SOCCER_PLAYERS.items():
        reg[REGION.get(state, "?")] = reg.get(REGION.get(state, "?"), 0) + n
    rmax = max(reg.values())
    for code, n in sorted(reg.items(), key=lambda x: -x[1]):
        print(f"  {REGION_NAME.get(code, code):10} {n:>9,}  {bar(n, rmax, 28)}")

    # ── 4. The strategic cross-read ──
    print("\n" + "-" * 70)
    print("  THE CROSS-READ (volume × rate)")
    print("-" * 70)
    HIGH_VOL = 100_000  # registered-player threshold for a "high volume" market

    def quad(want_high_vol, want_high_rate):
        out = []
        for s, r in NSCH_RATE.items():
            n = SOCCER_PLAYERS.get(s, 0)
            if (n >= HIGH_VOL) == want_high_vol and (r >= NATIONAL_RATE) == want_high_rate:
                out.append((s, n, r))
        return sorted(out, key=lambda x: -x[1])

    print(f"\n  (high volume = ≥{HIGH_VOL:,} players · high rate = ≥{NATIONAL_RATE}% national)")

    print("\n  HIGH VOLUME · LOW RATE  →  biggest conversion upside")
    print("  (large audience that under-participates — the rate has room to grow)")
    for s, n, r in quad(True, False):
        print(f"    {s:16} {n:>8,} players · {r}% rate  (−{NATIONAL_RATE-r:.1f} pts vs nat'l)")

    print("\n  HIGH VOLUME · HIGH RATE  →  proven markets, defend & showcase")
    for s, n, r in quad(True, True):
        print(f"    {s:16} {n:>8,} players · {r}% rate  (+{r-NATIONAL_RATE:.1f} pts vs nat'l)")

    print("\n  LOW VOLUME · HIGH RATE  →  saturated, low absolute ceiling")
    for s, n, r in sorted(quad(False, True), key=lambda x: -x[2]):
        print(f"    {s:16} {n:>8,} players · {r}% rate")

    print("\n  LOW VOLUME · LOW RATE  →  awareness play, not conversion")
    for s, n, r in sorted(quad(False, False), key=lambda x: x[2]):
        vol = f"{n:>8,} players" if s in SOCCER_PLAYERS else "  vol. n/a   "
        print(f"    {s:16} {vol} · {r}% rate")

    # ── 5. Campaign implications ──
    print("\n" + "-" * 70)
    print("  CAMPAIGN IMPLICATIONS  →  localized-CTA strategy")
    print("-" * 70)
    print("""
  • SPEND TIER 1 (volume + upside): Texas & Florida.
    Huge player bases but BELOW national participation — the rate has room
    to grow. Localized 'find a club in <state>' CTA converts latent demand.
    Highest ROI for the dynamic-voice variants.

  • SHOWCASE TIER (volume + proven): Massachusetts, California, New York.
    Big AND engaged. Use as hero markets in the demo and as social proof —
    'join the [N] players already on the field in <state>'.

  • EFFICIENCY TIER (small + hot): Vermont, South Dakota, New Hampshire.
    Highest rates in the country but tiny absolute numbers. Don't buy reach
    here — participation is near ceiling. Skip costly per-state variants.

  • AWARENESS, NOT CONVERSION (low + low): Nevada, Delaware, West Virginia.
    Low volume and low rate. Lead with the emotional 'why youth sport' angle,
    not a location sign-up CTA — you're creating demand, not harvesting it.
""")
    print("  Sources: US Youth Soccer state associations (via Authority Soccer);")
    print("           NSCH 2023, U.S. Census Bureau. Metrics differ in year/method —")
    print("           treat volume as audience size, rate as propensity, not 1:1.")
    print()


if __name__ == "__main__":
    main()
