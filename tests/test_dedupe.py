from datetime import datetime, timedelta, timezone

from src.robotics_daily.dedupe import CacheDB, canonicalize_url, content_hash


def test_canonicalize_url_removes_tracking_and_normalizes() -> None:
    raw = "HTTPS://Example.com/path/?utm_source=x&b=2&a=1#frag"
    got = canonicalize_url(raw)
    assert got == "https://example.com/path?a=1&b=2"


def test_cache_seen_recently(tmp_path) -> None:
    db = CacheDB(tmp_path / "cache.db")
    url = canonicalize_url("https://example.com/article?utm_source=abc")
    h = content_hash("hello world")
    assert db.seen_recently(url, h, days=30) is False
    db.mark_seen(url, h)
    assert db.seen_recently(url, h, days=30) is True


def test_cache_seen_by_hash_even_if_url_diff(tmp_path) -> None:
    db = CacheDB(tmp_path / "cache.db")
    h = content_hash("same content")
    db.mark_seen(canonicalize_url("https://example.com/a"), h)
    assert db.seen_recently(canonicalize_url("https://another.com/b"), h, days=30) is True
