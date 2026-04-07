from datetime import datetime, timezone

from src.robotics_daily.agents.base import AgentContext
from src.robotics_daily.agents.filter import FilterAgent
from src.robotics_daily.config import AppConfig
from src.robotics_daily.dedupe import CacheDB
from src.robotics_daily.models import SourceItem


def _make_ctx(tmp_path) -> AgentContext:
    return AgentContext(
        config=AppConfig(),
        cache=CacheDB(tmp_path / "cache.db"),
        output_dir=str(tmp_path),
    )


def _make_item(
    title: str = "Valid Robotics Article",
    url: str = "https://example.com/article",
    excerpt: str = "A long enough excerpt for testing purposes that passes the minimum length check easily.",
    source_type: str = "rss",
) -> SourceItem:
    return SourceItem(
        id="test",
        title=title,
        url=url,
        published_at=datetime.now(timezone.utc),
        source_type=source_type,
        raw_text_excerpt=excerpt,
        origin="test",
    )


class TestInMemoryFilter:
    def test_junk_url_dropped(self, tmp_path) -> None:
        ctx = _make_ctx(tmp_path)
        agent = FilterAgent()
        items = [_make_item(url="https://example.com/unsubscribe")]
        result = agent._in_memory_filter(ctx, items)
        assert len(result) == 0

    def test_privacy_url_dropped(self, tmp_path) -> None:
        ctx = _make_ctx(tmp_path)
        agent = FilterAgent()
        items = [_make_item(url="https://example.com/privacy")]
        result = agent._in_memory_filter(ctx, items)
        assert len(result) == 0

    def test_newsletter_homepage_dropped(self, tmp_path) -> None:
        ctx = _make_ctx(tmp_path)
        agent = FilterAgent()
        items = [_make_item(url="https://example.com/", source_type="newsletter_link")]
        result = agent._in_memory_filter(ctx, items)
        assert len(result) == 0

    def test_trivial_excerpt_dropped(self, tmp_path) -> None:
        ctx = _make_ctx(tmp_path)
        agent = FilterAgent()
        items = [_make_item(excerpt="too short")]
        result = agent._in_memory_filter(ctx, items)
        assert len(result) == 0

    def test_duplicate_title_dropped(self, tmp_path) -> None:
        ctx = _make_ctx(tmp_path)
        agent = FilterAgent()
        items = [
            _make_item(title="Same Title", url="https://a.com/1"),
            _make_item(title="Same Title", url="https://b.com/2"),
        ]
        result = agent._in_memory_filter(ctx, items)
        assert len(result) == 1

    def test_valid_item_kept(self, tmp_path) -> None:
        ctx = _make_ctx(tmp_path)
        agent = FilterAgent()
        items = [_make_item()]
        result = agent._in_memory_filter(ctx, items)
        assert len(result) == 1
        assert result[0].title == "Valid Robotics Article"

    def test_rss_homepage_not_dropped(self, tmp_path) -> None:
        """RSS items with path '/' should NOT be dropped (only newsletter_link)."""
        ctx = _make_ctx(tmp_path)
        agent = FilterAgent()
        items = [_make_item(url="https://example.com/", source_type="rss")]
        result = agent._in_memory_filter(ctx, items)
        assert len(result) == 1
