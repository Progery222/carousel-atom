"""End-to-end pipeline: news → filter → slides → caption.

Single entrypoint: `run_once(topic_slug, design_slug)`.
No delivery — Carousel Studio returns slide paths to the API caller.

Improvements over the original:
- Sources are fetched in parallel (small thread pool).
- Article enrichment (og:image / og:description / publish-time) runs
  in parallel — used to be a strict for-loop over slow HTTP fetches.
- Logging via `core.log` instead of `print`.
- Optional cross-topic dedup so the same Bleacher Report story doesn't
  show up in both NBA and Lifestyle on the same morning.
"""
from __future__ import annotations

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from core import dedup
from core.caption_engine import render_caption
from core.log import get_logger
from core.http import _download_one
from core.image_search import find_replacement_image
from core.parsers import enrich_article, fetch_html, fetch_newsapi, fetch_rss
from core.parsers.html_scraper import looks_low_res
from core.parsers.base import Article
from core.quality import balance_sources, passes_filters, score_article
from core.topic_loader import TopicConfig, load_topic
from designs import get_design

# Lazy import to keep `requests` out of the cold path for installs that
# don't use delivery at all.
def _maybe_deliver(topic: TopicConfig, slug: str, run_result: dict) -> dict | None:
    if not slug:
        return None
    from core.delivery import get_adapter
    adapter = get_adapter(slug)
    if not adapter.is_configured(topic):
        log.info("delivery '%s' not configured — skipping", slug)
        return {"adapter": slug, "skipped": True, "reason": "not configured"}
    res = adapter.send(topic, run_result)
    return {
        "adapter": slug,
        "ok": res.ok,
        "detail": res.detail,
        "message_ids": res.message_ids,
    }

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "output"
log = get_logger("pipeline")


def prune_old_runs(days: int) -> int:
    """Drop rendered run directories older than `days`, preserving anything
    still referenced from the dedup `posts` table (so studio history isn't
    broken). Returns the count of run directories removed."""
    from core.http import prune_dir_older_than
    if not OUTPUT_DIR.exists():
        return 0
    posted_ids = {p["run_id"] for p in dedup.recent_posts(limit=500)}
    total = 0
    for topic_dir in OUTPUT_DIR.iterdir():
        if not topic_dir.is_dir() or topic_dir.name.startswith("_"):
            continue
        total += prune_dir_older_than(topic_dir, days, keep_names=posted_ids)
    return total


def _fetch_source(src) -> list[Article]:
    if not getattr(src, "enabled", True):
        return []
    try:
        if src.kind == "rss":
            return fetch_rss(src.feed, src.name)
        if src.kind == "html":
            return fetch_html(src.url, src.article_pattern, src.name)
        if src.kind == "newsapi":
            return fetch_newsapi(
                src.query, src.name,
                domains=src.domains,
                language=src.language or "en",
                sort_by=src.sort_by or "publishedAt",
            )
        log.warning("unknown source kind: %s", src.kind)
        return []
    except Exception as e:
        log.warning("source %s failed: %s", src.name, e)
        return []


def _collect(topic: TopicConfig) -> list[Article]:
    """Pull every enabled source in parallel — IO-bound, threads are fine."""
    out: list[Article] = []
    enabled = [s for s in (topic.sources or []) if getattr(s, "enabled", True)]
    if not enabled:
        return out
    with ThreadPoolExecutor(max_workers=min(8, len(enabled))) as pool:
        for batch in pool.map(_fetch_source, enabled):
            out.extend(batch)
    return out


def _select_fresh(topic: TopicConfig, articles: list[Article],
                  *, cross_topic: bool = False) -> list[Article]:
    fresh = [
        a for a in articles
        if not dedup.is_seen(topic.slug, a.url, a.title)
        and not (cross_topic and dedup.is_seen_anywhere(a.url, a.title))
    ]
    log.info("%d/%d fresh articles", len(fresh), len(articles))
    return fresh


def _dedupe_batch(articles: list[Article]) -> list[Article]:
    """Drop near-identical titles within a single batch."""
    seen_keys: set[str] = set()
    out: list[Article] = []
    for a in articles:
        key = dedup.normalize_title(a.title)
        if key in seen_keys:
            log.debug("drop (in-batch dup): %s", a.title[:60])
            continue
        seen_keys.add(key)
        out.append(a)
    return out


def _ensure_image(article: Article) -> None:
    """Last-mile fallback: if an article still has no image (or only a
    low-res one) after `enrich_article`, search Wikimedia / Pexels /
    Unsplash for a topical replacement based on entities pulled from
    the title (and description, if needed).

    Mutates the article in place. Silent no-op if no source matches.
    """
    if article.image_url and not looks_low_res(article.image_url):
        return
    found = find_replacement_image(article.title, article.description)
    if found:
        article.image_url = found


# Verification cache lives next to the per-run output dirs so it survives
# across runs and the design's `download_images_parallel` becomes a cache
# hit instead of a second HTTP fetch.
_VERIFY_CACHE = OUTPUT_DIR / "_verify_cache"


# The photo-vs-graphic filter is heuristic and tuned to err on the side
# of false negatives. Enable it explicitly via env var when you want
# extra strictness; off by default so we never starve a carousel.
_PHOTO_FILTER_ENABLED = os.environ.get("CAROUSEL_PHOTO_FILTER", "").lower() in (
    "1", "true", "yes", "on",
)


def _verify_image_downloadable(article: Article) -> None:
    """Try to actually download the article's image. If anything goes
    wrong (404, unreachable, image too tiny to read, corrupt file), we
    clear `image_url` so the next pass through `passes_filters` drops
    the article. The pipeline will then pick the next-best candidate
    out of the score-ranked pool — much more honest than rendering an
    empty black slide.

    The optional photo-vs-graphic filter (logos / crests / composites)
    is gated by the CAROUSEL_PHOTO_FILTER env var. It's off by default
    because it's strict enough that an aggressive day of news can leave
    the pipeline empty.
    """
    if not article.image_url:
        return
    path = _download_one(article.image_url, _VERIFY_CACHE)
    if not path:
        log.info("image verify failed — dropping: %s", article.title[:60])
        article.image_url = ""
        return
    if _PHOTO_FILTER_ENABLED:
        # Local import keeps Pillow off the cold path when the filter
        # isn't in use.
        from core.image import is_press_photograph
        if not is_press_photograph(path):
            log.info("non-photo (logo/composite) — dropping: %s", article.title[:60])
            article.image_url = ""


def _enrich_and_filter(articles: list[Article],
                        blocklist: list[str] | None = None,
                        *,
                        min_keep_after_image_dedup: int = 0,
                        drop_reasons: dict[str, int] | None = None,
                        ) -> list[Article]:
    """Enrich (og:image/description) in parallel, then apply quality gate.

    `drop_reasons` is an optional dict that will be populated with a
    bucketed breakdown of why articles were filtered out — used by the
    API to surface "why empty" diagnostics to the studio frontend.
    """
    if not articles:
        return []

    # Stage 1: og:image / og:description / publish-time enrichment.
    # We trigger when the RSS-supplied image looks like a thumbnail too —
    # the enricher will swap to og:image, which is usually 1200x630.
    needs_enrich = [
        a for a in articles
        if not a.image_url or not a.description or looks_low_res(a.image_url)
    ]
    if needs_enrich:
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(enrich_article, needs_enrich))

    # Stage 2: image-search fallback. If an article *still* has no usable
    # image, hit Wikimedia/Pexels/Unsplash with the headline entities.
    # Wikimedia is the only one that helps reliably for sports/F1/NBA
    # (because famous athletes have Commons photos). Pexels/Unsplash are
    # a last resort and frequently miss specific news content — they
    # exist mostly so the chain doesn't crash if the user has set keys.
    needs_image = [
        a for a in articles
        if not a.image_url or looks_low_res(a.image_url)
    ]
    if needs_image:
        log.info("image-search fallback for %d article(s)", len(needs_image))
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(_ensure_image, needs_image))

    # Stage 3: verify the image actually downloads. This is the bit that
    # catches "URL returned 200 from the article page but the asset host
    # 404s" / "redirected to a login wall" / "Goal.com served an HTML
    # placeholder for the lazy-loaded thumb". When an article fails this
    # check we clear its image_url and let the next pass drop it.
    has_image = [a for a in articles if a.image_url]
    if has_image:
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(_verify_image_downloadable, has_image))

    enriched: list[Article] = []
    reasons: dict[str, int] = drop_reasons if drop_reasons is not None else {}
    for a in articles:
        ok, reason = passes_filters(a, blocklist=blocklist)
        if ok:
            enriched.append(a)
        else:
            # Bucket drops by short reason key for the survival summary.
            short = reason.split("(")[0].strip().rstrip(":") or reason
            reasons[short] = reasons.get(short, 0) + 1
            log.debug("drop (%s): %s", reason, a.title[:60])

    # Drop duplicates-by-image-URL. Pattern: F1.com puts the same
    # studio-set og:image on every "Cooldown Room" and "Beyond the Grid"
    # episode, so 5 different articles end up with the same hero shot.
    # The `min_keep` floor prevents this from leaving the carousel
    # short when the day's news genuinely doesn't have many unique heroes.
    enriched = _dedupe_images(enriched, min_keep=min_keep_after_image_dedup)

    log.info("enriched & verified: %d / %d articles survived",
             len(enriched), len(articles))
    if reasons:
        breakdown = ", ".join(f"{k}={v}" for k, v in sorted(
            reasons.items(), key=lambda kv: -kv[1]
        ))
        log.info("drop breakdown: %s", breakdown)
    return enriched


def _trending_bonuses(articles: list[Article]) -> dict[int, float]:
    """Cross-article entity overlap. If a name (Lewis Hamilton, Mudryk,
    Manchester City) appears in more than one article in the candidate
    pool, every article that mentions it gets a small score bump. The
    pattern catches "this is what everyone is writing about today" and
    pushes the truly hot stories to the top of the carousel.

    Returns a mapping article-id → bonus (additive on top of base score).
    """
    from collections import Counter
    from core.text import extract_entities

    entity_counts: Counter[str] = Counter()
    per_article: list[set[str]] = []
    for a in articles:
        ents = {e.lower() for e in extract_entities(a.title, max_terms=4)}
        per_article.append(ents)
        for e in ents:
            entity_counts[e] += 1

    bonuses: dict[int, float] = {}
    for a, ents in zip(articles, per_article):
        bonus = 0.0
        for e in ents:
            n = entity_counts[e]
            if n >= 3:
                bonus += 1.0  # genuine trending entity
            elif n >= 2:
                bonus += 0.4  # minor cross-source mention
        if bonus:
            bonuses[id(a)] = bonus
    return bonuses


def _dedupe_images(articles: list[Article],
                   *, min_keep: int = 0) -> list[Article]:
    """Drop articles whose image_url is a duplicate of an earlier one,
    BUT keep at least `min_keep` articles in the result by re-adding
    duplicates in score order if necessary.

    Why the soft floor: F1.com / NBA.com / Bleacher Report sometimes
    publish 5+ articles in a series that share the same hero image.
    A strict dedup leaves the carousel half-empty. Better to ship one
    duplicate-image slide than to ship a carousel with only 2 slides.
    """
    seen: set[str] = set()
    primary: list[Article] = []
    held: list[Article] = []  # duplicate-image articles, in score order
    for a in articles:
        url = a.image_url or ""
        if url and url in seen:
            held.append(a)
            continue
        if url:
            seen.add(url)
        primary.append(a)

    if len(primary) < min_keep and held:
        gap = min_keep - len(primary)
        primary.extend(held[:gap])
        log.info("image dedup short by %d — kept %d duplicate-image article(s)",
                 gap, min(gap, len(held)))
        held = held[gap:]
    if held:
        log.info("dropped %d article(s) with duplicate hero image", len(held))
    return primary


def run_once(topic_slug: str, design_slug: str = "newsflash",
             *, mark_seen: bool = True,
             cross_topic_dedup: bool = False,
             override_articles: list[Article] | None = None,
             deliver: str = "") -> dict:
    """Generate one carousel for `topic_slug` rendered with `design_slug`.

    Returns: {status, run_id, topic, design, slide_paths, caption, articles, output_dir}.

    `override_articles` lets the studio re-render an existing run with edited
    titles / replaced images without going back to the network.
    `deliver` is a delivery-adapter slug (e.g. "telegram") — empty disables.
    """
    dedup.init_db()
    topic = load_topic(topic_slug)
    design = get_design(design_slug)
    run_id = f"{topic.slug}_{design.slug}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    out_dir = OUTPUT_DIR / topic.slug / run_id
    t0 = time.monotonic()

    timings: dict[str, float] = {}
    # Counters surface to the API so the frontend can explain "why empty"
    # in actionable terms instead of a generic 409.
    diagnostics: dict[str, object] = {
        "raw": 0, "fresh": 0, "after_enrich": 0, "drop_reasons": {},
    }

    def _section(label: str, start: float) -> None:
        timings[label] = time.monotonic() - start

    if override_articles:
        selected = override_articles
        log.info("override mode: %d articles supplied", len(selected))
    else:
        t = time.monotonic()
        raw = _collect(topic)
        _section("collect", t)
        diagnostics["raw"] = len(raw)
        if not raw:
            return {"status": "no_articles", "run_id": run_id, "diagnostics": diagnostics}

        t = time.monotonic()
        fresh = _select_fresh(topic, raw, cross_topic=cross_topic_dedup)
        fresh = _dedupe_batch(fresh)
        _section("freshness", t)
        diagnostics["fresh"] = len(fresh)

        # Pre-rank with the cheap (HTTP-free) score so we only spend the
        # enrichment + verification budget on candidates that have a real
        # chance of making the cut. We over-provision by 5× so the
        # downstream image-URL dedup (which kills topical clusters like
        # F1.com's "Cooldown Room" series, where 5+ articles share the
        # same studio promo image) doesn't leave the carousel short.
        need = topic.carousel.news_per_carousel
        boost = topic.boost
        prelim = sorted(fresh, key=lambda a: -score_article(a, boost=boost))
        candidates = prelim[: max(need * 5, need + 10)]

        # Enrichment (og:image, image-search fallback) + verification
        # download. Articles whose image fails to download get their
        # image_url cleared and dropped by `passes_filters` here. The
        # topic's blocklist also runs at this stage so cross-sport bleed
        # (boxing/F1 leaking into a football feed) gets filtered out.
        # `min_keep_after_image_dedup` keeps the carousel from shrinking
        # to 2 slides when most candidates share the same hero photo.
        t = time.monotonic()
        drop_reasons: dict[str, int] = {}
        enriched = _enrich_and_filter(
            candidates,
            blocklist=topic.blocklist,
            min_keep_after_image_dedup=need,
            drop_reasons=drop_reasons,
        )
        _section("enrich+verify", t)
        diagnostics["after_enrich"] = len(enriched)
        diagnostics["drop_reasons"] = drop_reasons

        # Re-score after enrichment (descriptions/timestamps may now be
        # populated) and balance across sources. The trending pass adds
        # a bonus when an entity (Hamilton, Mudryk, Manchester City)
        # appears in multiple candidate articles — that's the signal
        # for "everyone's writing about this today, surface it".
        trending = _trending_bonuses(enriched)
        ranked = sorted(
            enriched,
            key=lambda a: -(score_article(a, boost=boost) + trending.get(id(a), 0.0)),
        )
        selected = balance_sources(ranked, need)
        if len(selected) < need:
            log.warning(
                "only %d usable articles (needed %d)",
                len(selected), need,
            )
            if not selected:
                return {"status": "no_usable", "run_id": run_id, "diagnostics": diagnostics}

        if mark_seen:
            dedup.mark_seen(
                [dedup.SeenRecord(topic.slug, a.url, a.title) for a in selected]
            )

    # Optional LLM headline rewrite. Topic opts in via
    # `caption.llm_rewrite_titles: true` in topic.yaml, and the global
    # LLM_API_KEY env var must be set. Each article's title gets the
    # @f1newsflash-style polish before the design touches it.
    if topic.caption.llm_rewrite_titles:
        t = time.monotonic()
        from core.llm import headline_rewriter
        rewriter = headline_rewriter()
        if rewriter:
            for a in selected:
                a.title = rewriter(a.title)
        _section("llm rewrite", t)

    t = time.monotonic()
    slide_paths = design.render(topic, selected, out_dir)
    _section("render", t)

    caption = render_caption(topic, selected)

    total = time.monotonic() - t0
    log.info(
        "run %s done in %.1fs · %d slides · %d articles",
        run_id, total, len(slide_paths), len(selected),
    )
    if timings:
        # Sort by descending duration so the slowest stage is most visible.
        breakdown = " · ".join(
            f"{k}={v:.1f}s" for k, v in sorted(timings.items(), key=lambda kv: -kv[1])
        )
        log.info("timings: %s", breakdown)

    result: dict = {
        "status": "ok",
        "run_id": run_id,
        "topic": topic.slug,
        "design": design.slug,
        "slide_paths": slide_paths,
        "caption": caption,
        "articles": [
            {
                "title": a.title,
                "url": a.url,
                "source": a.source,
                "image_url": a.image_url,
                "description": a.description,
            }
            for a in selected
        ],
        "output_dir": str(out_dir),
        "diagnostics": diagnostics,
    }
    delivery = _maybe_deliver(topic, deliver, result)
    if delivery:
        result["delivery"] = delivery
        if delivery.get("ok"):
            dedup.log_post(topic.slug, run_id, deliver, caption,
                           slide_count=len(slide_paths))
    return result


def select_fresh_candidates(
    topic_slug: str, *, exclude_urls: set[str] | None = None,
    count: int = 5,
) -> list[Article]:
    """Run the article-selection half of the pipeline (no render) and
    return `count` fresh Articles ready to feed `run_once(override_articles=…)`.

    `exclude_urls` is the set of URLs the caller already has and wants to
    keep (locked slides during a per-slide re-roll). Those are filtered
    out so the pipeline picks new ones.
    """
    dedup.init_db()
    topic = load_topic(topic_slug)
    raw = _collect(topic)
    if not raw:
        return []
    fresh = _select_fresh(topic, raw, cross_topic=False)
    fresh = _dedupe_batch(fresh)
    if exclude_urls:
        fresh = [a for a in fresh if a.url not in exclude_urls]
    boost = topic.boost
    prelim = sorted(fresh, key=lambda a: -score_article(a, boost=boost))
    candidates = prelim[: max(count * 5, count + 10)]
    enriched = _enrich_and_filter(
        candidates,
        blocklist=topic.blocklist,
        min_keep_after_image_dedup=count,
    )
    trending = _trending_bonuses(enriched)
    ranked = sorted(
        enriched,
        key=lambda a: -(score_article(a, boost=boost) + trending.get(id(a), 0.0)),
    )
    return balance_sources(ranked, count)


def preview_articles(topic_slug: str, *, limit: int = 12) -> dict:
    """Run the upstream half of the pipeline without rendering anything.

    Useful from the studio: surface what the pipeline *would* pick before
    spending CPU on rendering, so the operator can confirm the source mix
    looks right or hit "Reset seen" first.
    """
    dedup.init_db()
    topic = load_topic(topic_slug)
    raw = _collect(topic)
    fresh = _select_fresh(topic, raw)
    enriched = _enrich_and_filter(fresh)
    enriched = _dedupe_batch(enriched)
    ranked = sorted(enriched, key=lambda a: -score_article(a))
    top = ranked[:limit]
    return {
        "topic": topic.slug,
        "raw": len(raw),
        "fresh": len(fresh),
        "enriched": len(enriched),
        "candidates": [
            {
                "title": a.title,
                "url": a.url,
                "source": a.source,
                "image_url": a.image_url,
                "description": a.description,
                "score": round(score_article(a), 2),
            }
            for a in top
        ],
    }
