from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


SourceType = Literal["rss", "newsletter_link"]


@dataclass
class SourceItem:
    id: str
    title: str
    url: str
    published_at: datetime
    source_type: SourceType
    raw_text_excerpt: str
    origin: str
    score: float = 0.0
    summary_bullets: list[str] = field(default_factory=list)
    why_it_matters: str = ""


@dataclass
class PostDraftBundle:
    generated_at: datetime
    posts_markdown: str
    sources_used: list[SourceItem]
