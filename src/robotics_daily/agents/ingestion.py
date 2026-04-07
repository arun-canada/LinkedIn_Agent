from __future__ import annotations

from ..rss import fetch_rss_sources
from ..yahoo_imap import safe_fetch_newsletter_links
from .base import AgentContext, BaseAgent


class IngestionAgent(BaseAgent):
    """Fetches raw items from RSS feeds and email newsletters.

    Single responsibility: external I/O only. No filtering, deduplication, or enrichment.
    Writes ctx.raw_items.
    Sets ctx.should_continue = False if no items were fetched.
    """

    @property
    def name(self) -> str:
        return "IngestionAgent"

    def run(self, ctx: AgentContext) -> AgentContext:
        rss_items = fetch_rss_sources(ctx.config.rss_feeds, days_back=ctx.config.rss.days_back)
        self._log(ctx, "info", "Fetched %d RSS items", len(rss_items))

        mail_items = safe_fetch_newsletter_links(
            ctx.config.newsletter,
            ctx.yahoo_email,
            ctx.yahoo_password,
        )
        self._log(ctx, "info", "Fetched %d newsletter items", len(mail_items))

        ctx.raw_items = rss_items + mail_items
        self._log(ctx, "info", "Total raw items: %d", len(ctx.raw_items))

        if ctx.debug_mode:
            self._log(ctx, "debug", "─── Raw items ───")
            for i, item in enumerate(ctx.raw_items, 1):
                self._log(ctx, "debug", "  [%d] [%-16s] %s | from: %s",
                          i, item.source_type, item.title[:80], item.origin)

        if not ctx.raw_items:
            self._log(ctx, "warning", "No items fetched from any source — stopping pipeline")
            ctx.posts_markdown = "No items fetched today."
            ctx.should_continue = False

        return ctx
