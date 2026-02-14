from __future__ import annotations

from .models import SourceItem


def score_item(item: SourceItem, keywords: list[str]) -> float:
    text = f"{item.title} {item.raw_text_excerpt}".lower()
    score = 0.0
    for kw in keywords:
        if kw.lower() in text:
            score += 1.0
    # bias for source recency-ish via type
    if item.source_type == "newsletter_link":
        score += 0.25
    return score


def rank_items(items: list[SourceItem], keywords: list[str], max_items: int) -> list[SourceItem]:
    for item in items:
        item.score = score_item(item, keywords)
    ranked = sorted(items, key=lambda i: (i.score, i.published_at), reverse=True)
    return ranked[:max_items]
