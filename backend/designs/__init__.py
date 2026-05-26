"""Design registry. Add a new design module → import + register here."""
from designs.base import Design
from designs.blueprint import blueprint
from designs.editorial_white import editorial_white
from designs.highlight_reel import highlight_reel
from designs.newsflash import newsflash
from designs.polaroid import polaroid
from designs.premium_light import premium_light
from designs.quote_card import quote_card
from designs.quote_tweet import quote_tweet
from designs.seamless import seamless
from designs.story_mode import story_mode
from designs.tiktok_news import tiktok_news
from designs.viral_roundup import viral_roundup

# Order matters: the studio shows the first registered design as the
# default. `tiktok_news` is the closest match to the @f1newsflash
# reference, so it goes first.
_DESIGNS: dict[str, Design] = {
    tiktok_news.slug: tiktok_news,
    newsflash.slug: newsflash,
    editorial_white.slug: editorial_white,
    viral_roundup.slug: viral_roundup,
    quote_card.slug: quote_card,
    premium_light.slug: premium_light,
    story_mode.slug: story_mode,
    blueprint.slug: blueprint,
    seamless.slug: seamless,
    quote_tweet.slug: quote_tweet,
    highlight_reel.slug: highlight_reel,
    polaroid.slug: polaroid,
}


def list_designs() -> list[Design]:
    return list(_DESIGNS.values())


def get_design(slug: str) -> Design:
    if slug not in _DESIGNS:
        raise KeyError(f"Unknown design '{slug}'. Available: {list(_DESIGNS)}")
    return _DESIGNS[slug]
