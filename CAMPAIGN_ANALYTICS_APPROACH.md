# Geo-Priority Campaign Analytics — Reproducible Approach

A portable method for deciding **where to launch a geographically-targeted
campaign**. Built for US Youth Soccer (per-state), but written to generalize to
any brand, any set of geographic units (states, countries, cities, DMAs).

Feed this whole file to an AI agent (with web access + a charting/visual tool)
and it can reproduce the analysis for a new brand.

---

## 1. Objective

Rank geographic units by **launch priority** and produce a one-page dashboard
(heatmap + priority table + recommendation) that answers a single question:
**where should the campaign start, and why?**

The core thesis: priority is not just "where is the audience biggest." It is
**audience size weighted by conversion headroom** — a big market that is
*under-participating* is worth more than an equally big market that is already
saturated, because the campaign's localized call-to-action converts latent
demand rather than fighting for a maxed-out one.

---

## 2. The two signals (always collect both)

| Signal | What it measures | Typical source |
|--------|------------------|----------------|
| **Volume** | Absolute size of the addressable audience per unit | Registration/membership counts, customer counts, population of the target segment |
| **Rate** | Propensity / penetration — how intensely the unit already engages | Survey data, participation %, category penetration %, per-capita usage |

Volume tells you *how many people*; rate tells you *how much room is left*.
You need both. One without the other produces a misleading map.

### Data acquisition notes (learned the hard way)
- **Google Trends via `pytrends` is unreliable** — Google hard-blocks automated
  queries with HTTP 429 from most IPs, even with browser User-Agent headers.
  Do not depend on it for a live demo. If you need search-interest data, use a
  paid API (SerpApi, DataForSEO) or treat Trends as optional.
- **Prefer authoritative primary sources** for the rate signal (government
  surveys, official association data). For the US youth-sports case:
  - Volume: US Youth Soccer state-association registration counts.
  - Rate: NSCH (National Survey of Children's Health, US Census) — % of kids
    6–17 playing a sport, by state.
- **Interactive/JS dashboards (e.g. childhealthdata.org, Google Trends) often
  can't be scraped** — data lives in images or behind 403s. Find a secondary
  source that republishes the table, or use the primary microdata file.

---

## 3. Scoring methodology

For each geographic unit `g`:

```
volume_norm(g) = volume(g) / max(volume) * 100        # 0–100, biggest unit = 100
rate_factor(g) = NATIONAL_RATE / rate(g)              # <1 if above avg, >1 if below
                 = 1.0 if rate(g) is unknown          # neutral, and FLAG it
priority(g)    = volume_norm(g) * rate_factor(g)
```

- `rate_factor` boosts under-participating markets (headroom) and discounts
  saturated ones. A state with national-average rate scores on volume alone.
- **Never invent a rate to fill a gap.** If a unit has no verified rate, use
  factor 1.0 and explicitly flag it as volume-only in the output.

### Tiering (overlay on the score)
```
P1 launch · upside   : volume ≥ HIGH_VOL  AND  rate < national    (best — big + headroom)
P1 showcase          : volume ≥ HIGH_VOL  AND  rate ≥ national    (big + proven — social proof)
P1 launch            : volume ≥ HIGH_VOL  AND  rate unknown
P2 core              : HIGH_VOL > volume ≥ MID_VOL
P3 secondary         : MID_VOL  > volume ≥ LOW_VOL
P4 long-tail         : volume < LOW_VOL
efficient / skip     : volume < HIGH_VOL AND rate ≥ national       (saturated, small — don't buy reach)
```
Thresholds used for US states: `HIGH_VOL = 100k`, `MID_VOL = 50k`, `LOW_VOL = 25k`.
Scale these to your unit (countries vs cities have different magnitudes).

---

## 4. Output spec — one-page dashboard

Three elements, in this order:

1. **KPI cards** (4): "start here" (top 1–2 units), total audience, the national
   rate baseline, count of P1 units.
2. **Heatmap / choropleth** colored by `priority` score, bucketed into 4 bands
   (e.g. ≥40 / 20–40 / 10–20 / <10) plus a distinct "no data" gray. Hover shows
   the score. Use a single color ramp (one meaning = one ramp).
3. **Priority table** — top ~12 units: rank, unit, volume, rate (or "—"), score, tier.
4. **Recommendation** — exactly one paragraph: which units to launch in and why
   (name the upside markets), which to use as showcase, which to skip.

### Visualization rules that kept it clean
- One color ramp; legend always present when color encodes meaning.
- Round every displayed number (`toLocaleString`, `toFixed`).
- For US choropleths: `us-atlas@3/states-10m.json` + `d3.geoAlbersUsa()`, key
  data on `properties.name` (full state names). **Fetch the topology first** to
  confirm the key field before coding.
- Dark-mode safe: hardcode hex for canvas/SVG fills, CSS variables for HTML text.

---

## 5. Data-integrity rules (non-negotiable)

These are what make the analysis trustworthy rather than confident-but-wrong:

1. **Never fabricate a data point** to complete a table or map. Missing = "n/a",
   flagged, scored neutrally.
2. **State coverage explicitly** — "rate known for N/M units; the rest scored on
   volume alone." Don't let a partial map read as complete.
3. **Flag source/year mismatches** — if volume and rate come from different
   sources or years, say so; they are two lenses, not one index.
4. **Call out sleeper gaps** — a unit with no volume data but an extreme rate
   (e.g. Nevada, lowest US participation, but no registration count) may be a
   hidden opportunity; name it rather than dropping it silently.
5. **Cite every source** with a link.

---

## 6. Reusable prompt (copy-paste to another AI)

> You are a marketing analytics agent. For the brand **[BRAND]** running
> **[CAMPAIGN]**, build a geo-priority analysis over **[GEOGRAPHIC UNITS, e.g.
> US states]**.
>
> 1. Collect two signals per unit: **volume** (addressable audience size) and
>    **rate** (engagement/penetration propensity). Use authoritative sources;
>    cite each. Do not use pytrends/Google Trends as a hard dependency (429
>    blocking). Never fabricate a value — mark unknowns "n/a".
> 2. Score each unit: `priority = (volume / max_volume * 100) * (national_rate /
>    rate)`, with `rate_factor = 1.0` and a flag where rate is unknown.
> 3. Tier units (P1 launch/showcase, P2 core, P3 secondary, P4 long-tail,
>    efficient/skip) per the rules in this document.
> 4. Produce a one-page dashboard: 4 KPI cards, a choropleth/heatmap colored by
>    priority (4 buckets + no-data gray), a top-12 priority table, and a
>    one-paragraph recommendation naming the launch markets and the reasoning.
> 5. State coverage explicitly (how many units have a verified rate), flag any
>    source/year mismatch, and name any high-rate/no-volume sleeper markets.

---

## 7. Reference implementation

See `analyze_state_trends.py` in this repo for a working Python version of the
scoring + tiering + console report (US Youth Soccer, per-state). The dashboard
was rendered separately as an HTML/D3 + Chart.js widget following §4.
