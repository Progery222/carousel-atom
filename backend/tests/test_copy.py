"""Tests that verify hook/CTA defaults render and YAML overrides win."""
from core.copy import HookCopy, hook_copy, story_count_label
from core.topic_loader import (
    Brand, CarouselConfig, CaptionConfig, CTA, Schedule, Source, TopicConfig,
)


def _topic(**overrides):
    base = dict(
        slug="f1",
        display_name="F1 Daily",
        language="en",
        sources=[Source(kind="rss", name="x", feed="x")],
        brand=Brand(
            bg=(0, 0, 0),
            accent=(255, 0, 0),
            accent_light=(255, 100, 100),
        ),
        cta=CTA(headline="x"),
        caption=CaptionConfig(intro="x", hashtags=[]),
        carousel=CarouselConfig(),
        schedule=Schedule(),
    )
    base.update(overrides)
    return TopicConfig(**base)


def test_default_hook_used_when_pool_missing():
    h = hook_copy(_topic(), tone="viral", index=0)
    assert isinstance(h, HookCopy)
    assert "{n}" in h.line1


def test_yaml_override_wins():
    overrides = {
        "viral": [HookCopy("CUSTOM", "{n} {label}", "X", "Y", "a", "b", "")],
    }
    h = hook_copy(_topic(hook_pool=overrides), tone="viral", index=0)
    assert h.badge == "CUSTOM"


def test_severe_falls_back_to_viral_when_no_severe_pool():
    overrides = {"viral": [HookCopy("V", "{n}", "X", "Y", "a", "b", "")]}
    h = hook_copy(_topic(hook_pool=overrides), tone="severe", index=0)
    assert h.badge == "V"


def test_story_count_label_strips_suffix():
    assert story_count_label(_topic()) == "F1"
