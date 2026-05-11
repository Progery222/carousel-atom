"""Newsflash design — full-bleed photo top, bold bottom headline,
last-phrase accent in red, footer + segmented progress bar."""
from designs._newsflash_legacy import render_carousel as _render
from designs.base import Design

newsflash = Design(
    slug="newsflash",
    name="Newsflash",
    description=(
        "Full-bleed photo on top, massive headline below with the last "
        "1-2 words highlighted in red. Subtle footer with a brand mark "
        "and a segmented slide indicator."
    ),
    render=_render,
)
