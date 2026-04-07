from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
}


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    if netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]
    query_pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=False) if k.lower() not in TRACKING_PARAMS]
    query = urlencode(sorted(query_pairs))
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunparse((scheme, netloc, path, "", query, ""))


def content_hash(text: str) -> str:
    return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()


class CacheDB:
    def __init__(self, db_path: str | Path = "cache.db") -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._init_db()

    def _init_db(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_sources (
                canonical_url TEXT,
                content_hash TEXT,
                seen_at TEXT NOT NULL
            )
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_seen_url ON seen_sources(canonical_url)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_seen_hash ON seen_sources(content_hash)")
        self._conn.commit()

    def seen_recently(self, canonical_url: str, c_hash: str, days: int = 30) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        row = self._conn.execute(
            """
            SELECT 1
            FROM seen_sources
            WHERE (canonical_url = ? OR content_hash = ?)
              AND seen_at >= ?
            LIMIT 1
            """,
            (canonical_url, c_hash, cutoff.isoformat()),
        ).fetchone()
        return row is not None

    def mark_seen(self, canonical_url: str, c_hash: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO seen_sources(canonical_url, content_hash, seen_at) VALUES (?, ?, ?)",
            (canonical_url, c_hash, now),
        )
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None  # type: ignore[assignment]

    def __del__(self) -> None:
        self.close()
