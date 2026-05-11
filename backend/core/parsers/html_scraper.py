"""Generic HTML scraper. Falls back on og:* tags. Used when RSS isn't available
or sufficient. Drop-in replacement for the F1-style scraper.
"""
from __future__ import annotations

import html
import re

import requests
from bs4 import BeautifulSoup

from core import http as http_client
from core.log import get_logger
from core.parsers.base import Article

log = get_logger("parser.html")


def fetch_html(list_url: str, article_pattern: str, source_name: str,
               base_url: str = "", limit: int = 20) -> list[Article]:
    """Scrape a listing page; pull links matching `article_pattern`. Title comes from <a> text."""
    try:
        resp = http_client.get(list_url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        log.warning("%s list error: %s", source_name, e)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    if not base_url:
        # derive from list_url
        from urllib.parse import urlparse
        u = urlparse(list_url)
        base_url = f"{u.scheme}://{u.netloc}"

    out: list[Article] = []
    seen_urls: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if article_pattern not in href:
            continue
        url = href if href.startswith("http") else base_url + href
        if url in seen_urls:
            continue
        seen_urls.add(url)
        title = a.get_text(strip=True)
        if not title or len(title) < 10:
            continue
        out.append(Article(title=title, url=url, source=source_name))
        if len(out) >= limit:
            break

    log.info("%s: %d articles", source_name, len(out))
    return out


SITE_SUFFIXES = (
    " | Formula 1®", " - Formula 1", "Formula 1", " | F1.com", " | autosport",
    " | Autosport", " - Motorsport.com", " | Motorsport.com",
    " - ESPN", " | ESPN", " - Bleacher Report", " | Bleacher Report",
    " - The Athletic", " | The Athletic", " - NBA.com", " | NBA.com",
    " - NHL.com", " | NHL.com", " - MLB.com", " | MLB.com",
    " - MMA Fighting", " | MMA Fighting", " - MMA Junkie",
)


def _clean_title(title: str) -> str:
    """Decode HTML entities and strip duplicated/concatenated site-name junk."""
    t = html.unescape(title)
    for suf in SITE_SUFFIXES:
        if suf in t:
            t = t.split(suf, 1)[0]
    return " ".join(t.split()).strip(" -|·")


# URL fragments that are tell-tale signs of a small RSS thumbnail. When we
# spot one of these we know the og:image on the article page is almost
# always a 1200×630-ish press shot — worth the extra HTTP fetch.
_LOW_RES_URL_HINTS = (
    "/thumb", "/thumbs/", "/thumbnail", "_thumb.", "_thumbnail.",
    "/sm/", "/small/", "_sm.", "_small.",
    "/100x", "/120x", "/150x", "/180x", "/200x", "/250x", "/300x", "/400x",
    "/h2_lazy/", "/h2_default/",
    "?w=100", "?w=150", "?w=200", "?w=300", "?w=400", "?w=500",
)

# Regexes that try to extract a "width hint" embedded in the image URL.
# Each captures a single numeric group with the width.
_WIDTH_HINT_PATTERNS = (
    re.compile(r"/sport/(\d{2,4})/cpsprodpb/"),         # BBC sport (legacy)
    re.compile(r"/ace/standard/(\d{2,4})/cpsprodpb/"),  # BBC modern CDN
    re.compile(r"/news/(\d{2,4})/cpsprodpb/"),          # BBC news
    re.compile(r"/(\d{2,4})/master/"),                  # Guardian variant
    re.compile(r"/(\d{2,4})\.jpe?g$", re.IGNORECASE),   # Guardian: /2000.jpg
    re.compile(r"_(\d{2,4})x\d{2,4}\.", re.IGNORECASE), # _640x360.jpg
    re.compile(r"/w(\d{2,4})_"),                        # /w640_/
    re.compile(r"[?&]w=(\d{2,4})\b"),
    re.compile(r"[?&]width=(\d{2,4})\b"),
)


def url_width_hint(url: str) -> int:
    """Best-effort extraction of an image width encoded in the URL.

    Returns 0 if nothing recognisable is found. A return of `0` means
    "we don't know" — callers should not assume the image is small in
    that case.
    """
    if not url:
        return 0
    for pat in _WIDTH_HINT_PATTERNS:
        m = pat.search(url)
        if not m:
            continue
        try:
            return int(m.group(1))
        except (ValueError, IndexError):
            continue
    return 0


def looks_low_res(url: str) -> bool:
    """True if `url` smells like a thumbnail. Combines literal path hints
    with the numeric width extracted by `url_width_hint`.
    """
    if not url:
        return True
    u = url.lower()
    if any(h in u for h in _LOW_RES_URL_HINTS):
        return True
    w = url_width_hint(url)
    if 0 < w < 600:
        return True
    return False


# Mapping from "raw" publisher URL → high-res variant. Patterns are tuned
# against the publishers actually used by the bundled topic.yamls (BBC,
# Guardian, Goal, ESPN, Bleacher, NBA, F1.com). Each rule is a no-op if it
# doesn't match.
def upgrade_image_url(url: str) -> str:
    """Rewrite a low-res image URL to its known high-res variant.

    Conservative: only bumps a number to 2000-ish if the existing one is
    smaller. Same URL returned if no rule fires, so it's safe to call on
    every image.
    """
    if not url:
        return url
    out = url

    # Guardian: trailing /140.jpg, /460.jpg, /1000.jpg → /2000.jpg
    out = re.sub(
        r"/(\d{2,4})(\.jpe?g)$",
        lambda m: f"/2000{m.group(2)}" if int(m.group(1)) < 1500 else m.group(0),
        out, flags=re.IGNORECASE,
    )

    # BBC legacy sport CDN: /sport/<n>/cpsprodpb/ → /sport/2048/cpsprodpb/
    out = re.sub(
        r"/sport/(\d{2,4})/cpsprodpb/",
        lambda m: "/sport/2048/cpsprodpb/" if int(m.group(1)) < 1500 else m.group(0),
        out,
    )
    # BBC modern CDN (ichef.bbci.co.uk/ace/standard/<n>/cpsprodpb/...).
    # ichef caps `/ace/standard/` at 1024 — going higher 404s, so we
    # target 1024 exactly. Confirmed empirically against the 240×135
    # thumbs the soccer pipeline kept getting from BBC Sport football RSS.
    out = re.sub(
        r"/ace/standard/(\d{2,4})/cpsprodpb/",
        lambda m: "/ace/standard/1024/cpsprodpb/" if int(m.group(1)) < 900 else m.group(0),
        out,
    )
    # BBC News alt path
    out = re.sub(
        r"/news/(\d{2,4})/cpsprodpb/",
        lambda m: "/news/1024/cpsprodpb/" if int(m.group(1)) < 900 else m.group(0),
        out,
    )

    # Goal.com: /h2_lazy/, /h2_default/ → /h2_full/
    out = out.replace("/h2_lazy/", "/h2_full/")
    out = out.replace("/h2_default/", "/h2_full/")

    # Generic _640x360.jpg → _2000xN.jpg (preserving aspect ratio)
    def _bump_size(match):
        w = int(match.group(1))
        h = int(match.group(2))
        if w < 1200 and h > 0:
            new_w = 2000
            new_h = int(h * (new_w / w))
            return f"_{new_w}x{new_h}."
        return match.group(0)
    out = re.sub(r"_(\d{2,4})x(\d{2,4})\.", _bump_size, out)

    # ?w=150 / ?width=200 → 2000 if smaller
    out = re.sub(
        r"([?&])w=(\d{2,4})\b",
        lambda m: f"{m.group(1)}w=2000" if int(m.group(2)) < 1200 else m.group(0),
        out,
    )
    out = re.sub(
        r"([?&])width=(\d{2,4})\b",
        lambda m: f"{m.group(1)}width=2000" if int(m.group(2)) < 1200 else m.group(0),
        out,
    )

    # Twitter image host: ?name=<size> → ?name=large (1024px). The
    # `:large` URL form is older but still served — appended as a safety.
    out = re.sub(r"([?&])name=\w+", r"\1name=large", out)

    return out


def _largest_from_srcset(srcset: str) -> tuple[str, int]:
    """Parse an HTML srcset and return (url, width) of the largest entry.

    `srcset` looks like
        "https://x/100.jpg 100w, https://x/640.jpg 640w, https://x/2000.jpg 2000w"
    Returns ("", 0) when nothing parses.
    """
    if not srcset:
        return "", 0
    best_url, best_w = "", 0
    for piece in srcset.split(","):
        piece = piece.strip()
        if not piece:
            continue
        bits = piece.rsplit(" ", 1)
        if len(bits) != 2:
            url, descriptor = bits[0], ""
        else:
            url, descriptor = bits
        url = url.strip()
        if not url:
            continue
        width = 0
        if descriptor.endswith("w"):
            try:
                width = int(descriptor[:-1])
            except ValueError:
                width = 0
        if width >= best_w:
            best_w, best_url = width, url
    return best_url, best_w


def find_best_article_image(soup: "BeautifulSoup") -> str:
    """Sweep the article DOM for the highest-res hero image we can find.

    Priority:
      1. og:image — almost every site has it; treated as the baseline.
      2. twitter:image / twitter:image:src — sometimes higher res.
      3. <link rel="image_src"> — older standard, occasionally used.
      4. Largest entry from any <img srcset="..."> in the document.
      5. <picture><source srcset="..."> with the widest descriptor.
    Returns "" if nothing usable is found.
    """
    candidates: list[tuple[int, str]] = []

    def add(url: str, width_hint: int = 0) -> None:
        if not url:
            return
        url = url.strip()
        if not url:
            return
        # If we couldn't read a width, fall back to what's encoded in the URL.
        if width_hint <= 0:
            width_hint = url_width_hint(url) or 1200  # assume og standard
        candidates.append((width_hint, url))

    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        ow = soup.find("meta", property="og:image:width")
        try:
            wh = int(ow.get("content")) if ow and ow.get("content") else 0
        except ValueError:
            wh = 0
        add(og["content"], wh)

    tw = soup.find("meta", attrs={"name": "twitter:image:src"}) or \
         soup.find("meta", attrs={"name": "twitter:image"})
    if tw and tw.get("content"):
        add(tw["content"])

    img_src = soup.find("link", attrs={"rel": "image_src"})
    if img_src and img_src.get("href"):
        add(img_src["href"])

    for img in soup.find_all("img", attrs={"srcset": True})[:5]:
        url, w = _largest_from_srcset(img.get("srcset", ""))
        if url:
            add(url, w)

    for source in soup.find_all("source", attrs={"srcset": True})[:5]:
        url, w = _largest_from_srcset(source.get("srcset", ""))
        if url:
            add(url, w)

    if not candidates:
        return ""
    candidates.sort(key=lambda t: t[0], reverse=True)
    return candidates[0][1]


def enrich_article(article: Article) -> Article:
    """Fill image_url + description + better title from og: tags.

    Idempotent. Pipeline:
      1. First try a free URL upgrade (Guardian /140.jpg → /2000.jpg, BBC
         /sport/600/ → /sport/2048/, Goal /h2_lazy/ → /h2_full/, etc).
         No HTTP cost.
      2. If image still missing or still looks low-res, fetch the article
         page and lift `og:image` (also upgraded). `twitter:image` as a
         last-resort fallback.
      3. Same flow for description and title from `og:*` tags.
    """
    if article.image_url:
        upgraded = upgrade_image_url(article.image_url)
        if upgraded != article.image_url:
            article.image_url = upgraded

    needs_image = (not article.image_url) or looks_low_res(article.image_url)
    needs_desc = not article.description
    if not (needs_image or needs_desc):
        article.title = _clean_title(article.title)
        return article
    if not http_client.is_public_url(article.url):
        log.warning("enrich: refusing non-public URL %s", article.url[:80])
        article.title = _clean_title(article.title)
        return article
    try:
        resp = http_client.get(article.url, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        if needs_image:
            # Walk the article DOM (og:image, twitter:image, link rel=image_src,
            # <img srcset>, <picture><source srcset>) and pick the widest variant.
            new_img = find_best_article_image(soup)
            if new_img:
                new_img = upgrade_image_url(new_img)
                # Take the candidate if it's better, or our current one was
                # missing / low-res to begin with.
                if not looks_low_res(new_img) or looks_low_res(article.image_url):
                    article.image_url = new_img
        if not article.description or len(article.description) < 80:
            # Order: og:description (curated subtitle) → twitter:description
            # → article-body first <p> (fallback for sites that skimp on
            # social-card meta but still publish a real lead paragraph).
            new_desc = ""
            tag = soup.find("meta", property="og:description")
            if tag and tag.get("content"):
                new_desc = tag["content"].strip()
            if len(new_desc) < 80:
                t2 = soup.find("meta", attrs={"name": "twitter:description"})
                if t2 and t2.get("content"):
                    new_desc = t2["content"].strip()
            if len(new_desc) < 80:
                body_p = _first_article_paragraph(soup)
                if body_p and len(body_p) >= 80:
                    new_desc = body_p
            if new_desc and len(new_desc) > len(article.description or ""):
                article.description = new_desc[:500]
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            new_title = _clean_title(og_title["content"].strip())
            if new_title and len(new_title) > len(article.title) // 2:
                article.title = new_title
        # Try to extract a published timestamp so the freshness gate
        # actually works for HTML sources (was always None before).
        if article.published_ts is None:
            ts = _extract_published_ts(soup)
            if ts:
                article.published_ts = ts
    except requests.Timeout:
        log.debug("enrich timeout: %s", article.url[:80])
    except requests.ConnectionError as e:
        log.debug("enrich connect: %s (%s)", article.url[:80], e)
    except requests.HTTPError as e:
        status = getattr(e.response, "status_code", "?")
        log.debug("enrich http %s: %s", status, article.url[:80])
    except Exception as e:
        # Anything else (parser blew up on weird HTML, etc.) is more
        # surprising — surface it at warning level with a traceback.
        log.warning("enrich error for %s: %s", article.url[:60], e, exc_info=True)
    article.title = _clean_title(article.title)
    return article


def _first_article_paragraph(soup: "BeautifulSoup") -> str:
    """Find the first sensible-looking <p> inside the article body.

    Used when og:description is missing or too thin to make a slide
    body summary useful. We bias the search toward <article> / <main>
    containers and skip <p>s that are too short (likely picture
    captions or "By Author") or too long (likely full article body).
    """
    container = (
        soup.find("article")
        or soup.find("main")
        or soup.find(attrs={"role": "main"})
        or soup
    )
    for p in container.find_all("p", limit=10):
        text = p.get_text(strip=True)
        # Skip captions, bylines, dateline noise, ad-injected paragraphs.
        if not text or len(text) < 80:
            continue
        if text.lower().startswith(("by ", "image:", "photo:", "credit:")):
            continue
        if len(text) > 600:
            text = text[:600].rsplit(" ", 1)[0] + "…"
        return text
    return ""


def _extract_published_ts(soup: BeautifulSoup) -> int | None:
    """Best-effort published-time scrape. Tries several common og/article tags."""
    from email.utils import parsedate_to_datetime
    candidates = [
        ("meta", {"property": "article:published_time"}),
        ("meta", {"name":     "article:published_time"}),
        ("meta", {"property": "og:published_time"}),
        ("meta", {"itemprop": "datePublished"}),
        ("time", {}),
    ]
    for tag, attrs in candidates:
        node = soup.find(tag, attrs=attrs)
        if not node:
            continue
        raw = node.get("content") or node.get("datetime") or node.get_text(strip=True)
        if not raw:
            continue
        # ISO-8601 first, then RFC-2822 fallback
        try:
            from datetime import datetime
            return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp())
        except Exception:
            pass
        try:
            return int(parsedate_to_datetime(raw).timestamp())
        except Exception:
            pass
    return None
