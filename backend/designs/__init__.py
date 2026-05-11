"""Design registry. Add a new design module → import + register here."""
from designs.base import Design
from designs.blueprint import blueprint
from designs.newsflash import newsflash
from designs.premium_light import premium_light
from designs.quote_card import quote_card
from designs.story_mode import story_mode
from designs.tiktok_news import tiktok_news
from designs.viral_roundup import viral_roundup

# Order matters: the studio shows the first registered design as the
# default. `tiktok_news` is the closest match to the @f1newsflash
# reference, so it goes first.
_DESIGNS: dict[str, Design] = {
    tiktok_news.slug: tiktok_news,
    newsflash.slug: newsflash,
    viral_roundup.slug: viral_roundup,
    quote_card.slug: quote_card,
    premium_light.slug: premium_light,
    story_mode.slug: story_mode,
    blueprint.slug: blueprint,
}


def list_designs() -> list[Design]:
    return list(_DESIGNS.values())


def get_design(slug: str) -> Design:
    if slug not in _DESIGNS:
        raise KeyError(f"Unknown design '{slug}'. Available: {list(_DESIGNS)}")
    return _DESIGNS[slug]
