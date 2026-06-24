"""Extract dominant brand colours and scrape logo from a brand's homepage."""

import io
import re
import urllib.request
from urllib.parse import urljoin, urlparse


def _fetch_bytes(url: str, max_bytes: int = 500_000) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read(max_bytes)
    except Exception:
        return None


def _find_logo_url(html: str, base_url: str) -> str | None:
    """Return the best candidate logo URL from homepage HTML, in priority order."""

    # 1. apple-touch-icon — high-res, clean
    for pat in [
        r'<link[^>]+rel=["\']apple-touch-icon[^"\']*["\'][^>]+href=["\']([^"\']+)["\']',
        r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']apple-touch-icon[^"\']*["\']',
    ]:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return urljoin(base_url, m.group(1))

    # 2. Open Graph image
    for pat in [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    ]:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return urljoin(base_url, m.group(1))

    # 3. PNG favicon
    for pat in [
        r'<link[^>]+type=["\']image/png["\'][^>]+href=["\']([^"\']+)["\']',
        r'<link[^>]+href=["\']([^"\']+\.png)["\'][^>]+rel=["\'](?:shortcut )?icon["\']',
    ]:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return urljoin(base_url, m.group(1))

    # 4. <img> with "logo" in class / id / alt
    for attr_pat in [
        r'class=["\'][^"\']*logo[^"\']*["\']',
        r'id=["\'][^"\']*logo[^"\']*["\']',
        r'alt=["\'][^"\']*logo[^"\']*["\']',
    ]:
        for pat in [
            r'<img[^>]+' + attr_pat + r'[^>]+src=["\']([^"\']+)["\']',
            r'<img[^>]+src=["\']([^"\']+)["\'][^>]+' + attr_pat,
        ]:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                return urljoin(base_url, m.group(1))

    return None


def _dominant_from_image(image_bytes: bytes, n: int = 5) -> list[str]:
    """Return up to n dominant hex colours using Pillow median-cut quantisation."""
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes))

    if img.mode in ("RGBA", "LA", "P"):
        if img.mode == "P":
            img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")

    img = img.resize((150, 150), Image.LANCZOS)
    quantized = img.quantize(colors=n)
    palette = quantized.getpalette()[: n * 3]

    colours = []
    for i in range(n):
        r, g, b = palette[i * 3], palette[i * 3 + 1], palette[i * 3 + 2]
        if r > 245 and g > 245 and b > 245:
            continue
        colours.append(f"#{r:02x}{g:02x}{b:02x}")
    return colours


def _extract_css_colours(html: str) -> list[str]:
    """Return unique non-neutral hex colour values found in raw HTML/CSS."""
    seen: dict[str, None] = {}
    for m in re.finditer(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", html):
        raw = m.group(0).lower()
        h = raw if len(raw) == 7 else f"#{raw[1]*2}{raw[2]*2}{raw[3]*2}"
        r, g, b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
        if r == g == b:
            continue
        if r > 240 and g > 240 and b > 240:
            continue
        if r < 15 and g < 15 and b < 15:
            continue
        seen[h] = None
    return list(seen.keys())[:10]


def scrape_logo(brand_url: str) -> bytes | None:
    """Download the brand logo image scraped from the homepage. Returns raw bytes or None."""
    if not brand_url:
        return None
    url = brand_url if "://" in brand_url else f"https://{brand_url}"
    html_bytes = _fetch_bytes(url)
    if not html_bytes:
        return None
    html = html_bytes.decode("utf-8", errors="replace")
    logo_url = _find_logo_url(html, url)
    if not logo_url:
        print("[colours] No logo URL found on homepage")
        return None
    print(f"[colours] Found logo at {logo_url}")
    return _fetch_bytes(logo_url, max_bytes=2_000_000)


def extract(brand_url: str) -> dict:
    """
    Return dominant colour data extracted from the brand website's CSS.

    Result shape:
      {"web_colours": ["#hex", ...]}

    Empty on failure; callers should treat this as non-fatal.
    """
    if not brand_url:
        return {"web_colours": []}

    url = brand_url if "://" in brand_url else f"https://{brand_url}"
    html_bytes = _fetch_bytes(url)
    html = html_bytes.decode("utf-8", errors="replace") if html_bytes else ""

    web_colours: list[str] = []
    if html:
        web_colours = _extract_css_colours(html)
        if web_colours:
            print(f"[colours] Web CSS colours: {web_colours[:5]}")

    return {"web_colours": web_colours}
