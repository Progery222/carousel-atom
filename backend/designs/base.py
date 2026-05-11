"""Design plugin protocol. Each design renders the same input
(topic + articles) into a folder of PNG slides."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from core.parsers.base import Article
from core.topic_loader import TopicConfig


class DesignRenderer(Protocol):
    def __call__(
        self, topic: TopicConfig, articles: list[Article], output_dir: Path
    ) -> list[str]: ...


@dataclass(frozen=True)
class Design:
    slug: str
    name: str
    description: str
    render: DesignRenderer
