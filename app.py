"""
Dynamic Voice API — Streamlit demo app
PMG × Luma AI Hackathon 2026

Run: streamlit run app.py
"""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Dynamic Voice API",
    page_icon="🎙️",
    layout="wide",
)

# ── Session state ─────────────────────────────────────────────────────────────

for k, v in {
    "brand_url":       "",
    "campaign":        "",
    "brand":           None,
    "context":         None,
    "trends":          None,
    "locations":       None,
    "run_id":          None,
    "default_audio":   None,
    "localized":       [],
    "translated":      [],
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Constants ─────────────────────────────────────────────────────────────────

BASE = "https://v2.api.audio"

LANGUAGES = {
    "English (US)":    {"lang": "en", "accent": ["american"]},
    "English (UK)":    {"lang": "en", "accent": ["british"]},
    "French":          {"lang": "fr", "accent": ["french"]},
    "Spanish":         {"lang": "es", "accent": ["spanish"]},
    "Portuguese (BR)": {"lang": "pt", "accent": ["portuguese"]},
    "German":          {"lang": "de", "accent": ["german"]},
    "Italian":         {"lang": "it", "accent": ["italian"]},
    "Dutch":           {"lang": "nl", "accent": ["dutch"]},
}

# ── Helpers ───────────────────────────────────────────────────────────────────

@st.cache_resource
def _get_client():
    from anthropic import Anthropic
    return Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def _as_headers() -> dict:
    return {
        "x-api-key":    os.getenv("AUDIOSTACK_API_KEY", ""),
        "x-assume-org": os.getenv("AUDIOSTACK_ORG_ID", ""),
    }


def _poll(af_id: str, timeout: int = 180) -> str | None:
    h = {**_as_headers(), "version": "4"}
    for _ in range(timeout // 3):
        r = requests.get(f"{BASE}/audioforms/{af_id}", headers=h)
        if r.status_code == 200:
            return r.json()["data"].get("result", {}).get("delivery", {}).get("uri")
        time.sleep(3)
    return None


def _submit_brief(body: dict) -> str:
    r = requests.post(f"{BASE}/creator/brief", headers=_as_headers(), json=body)
    r.raise_for_status()
    return r.json()["data"]["audioforms"][0]["audioformId"]


def _make_brief(product_name, description, cta, audience, tone,
                lang="en", accent=None) -> dict:
    return {
        "audioformVersion": "2",
        "engine":           "agentic",
        "brief": {
            "script": {
                "productName":        product_name,
                "productDescription": description[:500],
                "lang":               lang,
                "callToAction":       cta,
                "targetAudience":     audience,
                "toneOfScript":       tone,
            },
            "voices":  [{"accent": accent or ["american"], "voicePreset": "expressive"}],
            "sounds":  {"soundDesign": {"useSmartFit": True}},
            "delivery": {
                "loudnessPreset": "streaming",
                "encoderPreset":  "wav",
                "public":         True,
            },
        },
        "numAds": 1,
    }


def _brief_defaults() -> dict:
    b = st.session_state.brand or {}
    c = st.session_state.context or {}
    tone_raw = b.get("tone_of_voice", [])
    return {
        "product_name": b.get("brand_name", ""),
        "description":  f"{c.get('campaign_angle', '')}. {b.get('mission', '')}".strip(". "),
        "cta":          b.get("cta", ""),
        "audience":     b.get("target_audience", ""),
        "tone":         ", ".join(tone_raw) if isinstance(tone_raw, list) else str(tone_raw),
    }


# ── Header ────────────────────────────────────────────────────────────────────

st.title("🎙️ Dynamic Voice API")
st.caption("PMG × Luma AI — Hackathon 2026 · AI-powered localized audio ads at scale")

tab1, tab2, tab3, tab4 = st.tabs([
    "📋 Brief & Default Ad",
    "📍 Location Versions",
    "🌍 Translate",
    "📈 Trends & Traffic",
])

# ── Tab 1 — Brief & Default Ad ────────────────────────────────────────────────

with tab1:
    st.subheader("Brand & Campaign")

    col_a, col_b = st.columns([1, 2])
    with col_a:
        brand_url = st.text_input(
            "Brand URL",
            value=st.session_state.brand_url,
            placeholder="https://www.usyouthsoccer.org",
        )
    with col_b:
        campaign = st.text_area(
            "Campaign Description",
            value=st.session_state.campaign,
            placeholder="Summer sign-up push targeting parents of kids 6–18 across the US",
            height=78,
        )

    if st.button("🔍 Fetch Brand & Campaign Data", disabled=not (brand_url and campaign)):
        st.session_state.brand_url = brand_url
        st.session_state.campaign  = campaign
        client = _get_client()

        with st.spinner("Fetching brand corpus…"):
            from feeds import brand as brand_feed
            st.session_state.brand = brand_feed.fetch(client, url=brand_url)

        with st.spinner("Fetching campaign context…"):
            from feeds import context as context_feed
            st.session_state.context = context_feed.fetch(client, query=campaign)

        import db
        db.init()
        st.session_state.run_id = db.create_run(brand_url, campaign)
        db.save_brand(st.session_state.run_id, st.session_state.brand)
        db.save_context(st.session_state.run_id, st.session_state.context)
        st.success(f"Data ready — Run #{st.session_state.run_id}")

    if st.session_state.brand:
        with st.expander("Brand corpus", expanded=False):
            st.json(st.session_state.brand)
        with st.expander("Campaign context", expanded=False):
            st.json(st.session_state.context)

        st.divider()
        st.subheader("Ad Brief")
        st.caption("Auto-filled from brand data — edit before generating.")

        f = _brief_defaults()
        col_a, col_b = st.columns(2)
        with col_a:
            p_name   = st.text_input("Product Name",    value=f["product_name"], key="t1_name")
            audience = st.text_input("Target Audience", value=f["audience"],     key="t1_aud")
            cta      = st.text_input("Call to Action",  value=f["cta"],          key="t1_cta")
        with col_b:
            tone        = st.text_input("Tone",        value=f["tone"],        key="t1_tone")
            description = st.text_area("Description",  value=f["description"], key="t1_desc", height=100)

        if st.button("🎙️ Generate Default Ad"):
            body = _make_brief(p_name, description, cta, audience, tone)
            with st.spinner("Submitting brief to Audiostack… (~30s)"):
                af_id = _submit_brief(body)
                url   = _poll(af_id)
            if url:
                st.session_state.default_audio = url
            else:
                st.error("Timed out — try again.")

    if st.session_state.default_audio:
        st.divider()
        st.subheader("Default Ad")
        st.audio(st.session_state.default_audio)
        st.caption(st.session_state.default_audio)

# ── Tab 2 — Location Versions ─────────────────────────────────────────────────

with tab2:
    st.subheader("Location-Based Versions")

    if not st.session_state.run_id:
        st.info("Complete Tab 1 first — fetch brand & campaign data.")
    else:
        if st.button("📍 Fetch Locations from Brand Website"):
            client = _get_client()
            with st.spinner("Scraping locations…"):
                from feeds import locations as loc_feed
                loc_data = loc_feed.fetch(
                    client,
                    brand_url=st.session_state.brand_url,
                    brand_name=(st.session_state.brand or {}).get("brand_name", ""),
                )
            st.session_state.locations = loc_data
            import db
            db.save_locations(st.session_state.run_id, loc_data)
            count = len(loc_data.get("locations", []))
            st.success(f"Found {count} locations")

        if st.session_state.locations:
            locs     = st.session_state.locations.get("locations", [])
            all_names = [l["name"] for l in locs]

            col_a, col_b = st.columns([3, 1])
            with col_a:
                selected = st.multiselect(
                    f"Select locations ({len(locs)} available)",
                    all_names,
                    default=all_names[:5],
                )
            with col_b:
                st.metric("Selected", len(selected))

            if st.button("🎙️ Generate Localized Ads", disabled=not selected):
                f           = _brief_defaults()
                t           = st.session_state.trends or {}
                trend_line  = t.get("traffic_signal", "")
                description = (f"{f['description']}. Trend: {trend_line}".strip(". ")
                               if trend_line else f["description"])

                loc_map  = {l["name"]: l.get("cta_suffix", l["name"]) for l in locs}
                sel_locs = [{"name": n, "cta_suffix": loc_map[n]} for n in selected]

                progress = st.progress(0, text="Submitting briefs…")
                results  = []

                def _gen_one(loc):
                    cta_loc = f"{f['cta']} — {loc['cta_suffix']}"
                    body    = _make_brief(f["product_name"], description, cta_loc,
                                         f["audience"], f["tone"])
                    af_id   = _submit_brief(body)
                    url     = _poll(af_id)
                    return {
                        "location":  loc["name"],
                        "audio_url": url or "",
                        "status":    "complete" if url else "timeout",
                    }

                with ThreadPoolExecutor(max_workers=5) as pool:
                    futs = {pool.submit(_gen_one, loc): i for i, loc in enumerate(sel_locs)}
                    for done, fut in enumerate(as_completed(futs)):
                        results.append(fut.result())
                        progress.progress((done + 1) / len(sel_locs),
                                          text=f"{done + 1}/{len(sel_locs)} complete")

                st.session_state.localized = results
                import db
                db.save_audio_outputs(st.session_state.run_id, results)
                progress.empty()

        if st.session_state.localized:
            st.divider()
            complete = [r for r in st.session_state.localized if r["status"] == "complete"]
            st.caption(f"{len(complete)}/{len(st.session_state.localized)} rendered")
            for r in sorted(st.session_state.localized, key=lambda x: x["location"]):
                col_a, col_b = st.columns([1, 3])
                with col_a:
                    st.write(f"**{r['location']}**")
                with col_b:
                    if r["audio_url"]:
                        st.audio(r["audio_url"])
                    else:
                        st.caption("⚠️ timed out")

# ── Tab 3 — Translate ─────────────────────────────────────────────────────────

with tab3:
    st.subheader("Translate to Another Language")

    if not st.session_state.brand:
        st.info("Complete Tab 1 first — fetch brand & campaign data.")
    else:
        f = _brief_defaults()

        col_a, col_b = st.columns([1, 1])
        with col_a:
            lang_choice = st.selectbox("Target Language", list(LANGUAGES.keys()))
            lang_cfg    = LANGUAGES[lang_choice]
        with col_b:
            cta_translated = st.text_input(
                "Call to Action (in target language)",
                value=f["cta"],
                help="Translate the CTA for best results",
            )

        st.caption(f"Will generate with lang=`{lang_cfg['lang']}`, accent=`{lang_cfg['accent']}`")

        if st.button(f"🌍 Generate in {lang_choice}"):
            body = _make_brief(
                f["product_name"], f["description"], cta_translated,
                f["audience"], f["tone"],
                lang=lang_cfg["lang"], accent=lang_cfg["accent"],
            )
            with st.spinner(f"Generating {lang_choice} ad… (~30s)"):
                af_id = _submit_brief(body)
                url   = _poll(af_id)

            if url:
                # replace existing entry for this language
                others = [r for r in st.session_state.translated if r["lang"] != lang_choice]
                st.session_state.translated = others + [{"lang": lang_choice, "audio_url": url}]
            else:
                st.error("Timed out — try again.")

        if st.session_state.translated:
            st.divider()
            for r in st.session_state.translated:
                col_a, col_b = st.columns([1, 3])
                with col_a:
                    st.write(f"**{r['lang']}**")
                with col_b:
                    st.audio(r["audio_url"])
                    st.caption(r["audio_url"])

# ── Tab 4 — Trends & Traffic ──────────────────────────────────────────────────

with tab4:
    st.subheader("Trends & Traffic Baseline")

    if not st.session_state.run_id:
        st.info("Complete Tab 1 first — fetch brand & campaign data.")
    else:
        if st.button("📈 Fetch Trend Signal"):
            client = _get_client()
            b = st.session_state.brand or {}

            with st.spinner("Deriving keywords from brand & campaign…"):
                import sys
                sys.path.insert(0, str(Path(__file__).parent))
                from fetch_feeds import derive_keywords
                keywords = derive_keywords(client, b, st.session_state.campaign)

            with st.spinner("Fetching SimilarWeb traffic + Google Trends (parallel)…"):
                from feeds import trends as trends_feed
                trend_data = trends_feed.fetch(
                    client=client,
                    brand_url=st.session_state.brand_url,
                    keywords=keywords,
                )

            st.session_state.trends = trend_data
            import db
            db.save_trends(st.session_state.run_id, trend_data)

        if st.session_state.trends:
            t  = st.session_state.trends
            wt = t.get("website_traffic", {})
            st_data = t.get("search_trends", {})

            # ── Website traffic ──
            st.markdown("#### Website Traffic")
            if wt.get("available"):
                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    visits = wt.get("monthly_visits")
                    st.metric("Monthly Visits", f"{visits:,}" if visits else "—")
                with col_b:
                    change = wt.get("visit_change_pct")
                    st.metric("MoM Change", f"{change:+.1f}%" if change is not None else "—",
                              delta=change)
                with col_c:
                    bounce = wt.get("bounce_rate")
                    st.metric("Bounce Rate", f"{bounce:.1f}%" if bounce is not None else "—")

                if wt.get("top_pages"):
                    st.write("**Top Pages**")
                    for page in wt["top_pages"]:
                        st.write(f"- {page}")

                if wt.get("signal"):
                    st.info(wt["signal"])
            else:
                st.warning(f"Website traffic unavailable — {wt.get('reason', 'no data')}")

            # ── Search trends ──
            st.markdown("#### Search Trends (Google, past 7 days)")
            if st_data.get("available"):
                scores = st_data.get("interest_scores", {})
                if scores:
                    st.bar_chart(scores)

                col_a, col_b = st.columns(2)
                with col_a:
                    st.metric("Peak Keyword", st_data.get("peak_keyword", "—"))
                with col_b:
                    rising = st_data.get("rising_queries", [])
                    st.write("**Rising Queries**")
                    for q in rising:
                        st.write(f"- {q}")

                if st_data.get("signal"):
                    st.info(st_data["signal"])
            else:
                st.warning(f"Search trends unavailable — {st_data.get('reason', 'no data')}")

            # ── Combined signal ──
            if t.get("traffic_signal"):
                st.divider()
                st.markdown("#### Combined Signal")
                st.success(t["traffic_signal"])
