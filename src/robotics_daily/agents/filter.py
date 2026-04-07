from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from ..dedupe import canonicalize_url, content_hash
from ..extract import enrich_source_excerpt
from ..models import SourceItem
from ..utils import JUNK_URL_RE as _JUNK_PATH_RE
from .base import AgentContext, BaseAgent


def _enrich_one(item: SourceItem) -> tuple[SourceItem, str, str, str]:
    """Enrich a single item: canonicalize URL, fetch full text, compute hash."""
    canonical = canonicalize_url(item.url)
    excerpt = enrich_source_excerpt(canonical, item.raw_text_excerpt)
    c_hash = content_hash(excerpt or item.title)
    return item, canonical, excerpt, c_hash


class FilterAgent(BaseAgent):
    """Cleans and deduplicates raw items, enriches excerpts, and checks the persistent cache.

    Single responsibility: transform raw_items into validated_items ready for scoring.

    Steps (each logged separately for observability):
      1. Junk URL filter — drop privacy/terms/unsubscribe pages
      2. Within-run dedup — drop items sharing a title or content hash this run
      3. Excerpt enrichment — fetch full article text via extract.py (parallelized)
      4. Cache dedup — skip items seen in the last 30 days (cross-run)

    Writes ctx.validated_items and ctx.url_to_hash.
    Sets ctx.should_continue = False if 0 items survive all filters.
    """

    @property
    def name(self) -> str:
        return "FilterAgent"

    def run(self, ctx: AgentContext) -> AgentContext:
        # --- Pass 1: junk URLs + within-run dedup ---
        pre_filter = self._in_memory_filter(ctx, ctx.raw_items)
        self._log(
            ctx, "info",
            "In-memory filter: %d → %d items (dropped %d)",
            len(ctx.raw_items), len(pre_filter), len(ctx.raw_items) - len(pre_filter),
        )

        if ctx.debug_mode:
            self._log(ctx, "debug", "─── After in-memory filter ───")
            for i, item in enumerate(pre_filter, 1):
                self._log(ctx, "debug", "  [%d] [%-16s] %s",
                          i, item.source_type, item.title[:80])

        # --- Pass 2: enrich excerpts in parallel + sequential cache dedup ---
        enriched: list[SourceItem] = []
        url_to_hash: dict[str, str] = {}

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(_enrich_one, pre_filter))

        for item, canonical, excerpt, c_hash in results:
            if ctx.cache.seen_recently(canonical, c_hash, days=30):
                self._log(ctx, "debug", "Cache hit, skipping: %s", canonical)
                continue
            item.url = canonical
            item.raw_text_excerpt = excerpt
            url_to_hash[canonical] = c_hash
            enriched.append(item)

        self._log(
            ctx, "info",
            "Cache dedup: %d → %d items (%d already seen)",
            len(pre_filter), len(enriched), len(pre_filter) - len(enriched),
        )

        if ctx.debug_mode:
            self._log(ctx, "debug", "─── Validated items (passed all filters) ───")
            for i, item in enumerate(enriched, 1):
                excerpt_preview = (item.raw_text_excerpt or "")[:120].replace("\n", " ")
                self._log(ctx, "debug", "  [%d] %s\n        url: %s\n        excerpt: %s…",
                          i, item.title[:80], item.url, excerpt_preview)

        ctx.validated_items = enriched
        ctx.url_to_hash = url_to_hash

        if not ctx.validated_items:
            self._log(ctx, "warning", "No items survived filtering — stopping pipeline")
            ctx.posts_markdown = "No new high-relevance items found today."
            ctx.should_continue = False

        return ctx

    def _in_memory_filter(self, ctx: AgentContext, items: list[SourceItem]) -> list[SourceItem]:
        kept: list[SourceItem] = []
        seen_title_norms: set[str] = set()
        seen_content_hashes: set[str] = set()

        for item in items:
            url_lower = item.url.lower()
            parsed = urlparse(item.url)

            # 1. Junk URL paths
            if _JUNK_PATH_RE.search(url_lower):
                self._log(ctx, "debug", "Dropped junk URL: %s", item.url)
                continue

            # 2. Bare newsletter homepages (no article path)
            if item.source_type == "newsletter_link" and parsed.path in ("", "/"):
                self._log(ctx, "debug", "Dropped newsletter homepage: %s", item.url)
                continue

            # 3. Trivially short excerpt — no real content extracted
            if len(item.raw_text_excerpt.strip()) < 30:
                self._log(ctx, "debug", "Dropped trivial excerpt: %s | %s", item.title, item.url)
                continue

            # 4. Duplicate title within this run
            title_norm = re.sub(r"\s+", " ", (item.title or "").strip().lower())
            if title_norm and title_norm in seen_title_norms:
                self._log(ctx, "debug", "Dropped duplicate title: %s", item.title)
                continue

            # 5. Duplicate content hash within this run (same email body → multiple links)
            c_hash = content_hash(item.raw_text_excerpt or item.title)
            if c_hash in seen_content_hashes:
                self._log(ctx, "debug", "Dropped duplicate content: %s | %s", item.title, item.url)
                continue

            seen_title_norms.add(title_norm)
            seen_content_hashes.add(c_hash)
            kept.append(item)

        return kept
