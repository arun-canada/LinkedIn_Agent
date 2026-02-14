from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

import feedparser

from .config import RSSFeed
from .models import SourceItem

logger = logging.getLogger(__name__)


def _parse_date(entry: feedparser.FeedParserDict) -> datetime:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return datetime.now(timezone.utc)
    return datetime(*parsed[:6], tzinfo=timezone.utc)


def fetch_rss_sources(feeds: list[RSSFeed]) -> list[SourceItem]:
    items: list[SourceItem] = []
    for feed in feeds:
        try:
            parsed = feedparser.parse(feed.url)
            for entry in parsed.entries:
                url = entry.get("link", "").strip()
                title = entry.get("title", "Untitled").strip()
                summary = (entry.get("summary") or "").strip()
                if not url:
                    continue
                item_id = hashlib.md5(f"rss:{url}".encode("utf-8")).hexdigest()  # nosec B324
                items.append(
                    SourceItem(
                        id=item_id,
                        title=title,
                        url=url,
                        published_at=_parse_date(entry),
                        source_type="rss",
                        raw_text_excerpt=summary,
                        origin=feed.name,
                    )
                )
        except Exception as exc:
            logger.exception("RSS ingestion failed for %s: %s", feed.url, exc)
    return items
