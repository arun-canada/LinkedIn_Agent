from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


SourceType = Literal["rss", "newsletter_link"]
QualityFlag = Literal["publish", "review", "skip"]


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
    reflection: str = ""


@dataclass
class PostRecommendation:
    item_title: str
    item_url: str
    item_score: float
    quality_flag: QualityFlag  # "publish" | "review" | "skip"
    reason: str                # one-liner explanation for the recommendations table
    post_index: int            # 1-based index into posts_markdown drafts
