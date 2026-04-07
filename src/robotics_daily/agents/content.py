from __future__ import annotations

from ..llm import generate_posts, summarize_items
from ..models import SourceItem
from .base import AgentContext, BaseAgent


def _fallback_posts(items: list[SourceItem]) -> str:
    """Minimal static post draft used when the LLM is unavailable."""
    chunks = [
        "Quick roundup from today in autonomy + robotics:\n",
    ]
    for item in items[:6]:
        chunks.append(f"- {item.title} ({item.url})")
    chunks.append("\n#Robotics #Autonomy #Simulation #Automation #Validation")
    return "\n".join(chunks)


class ContentAgent(BaseAgent):
    """Calls the LLM to summarize items and generate LinkedIn post drafts.

    Two sequential LLM operations are kept in one agent because they are always
    run together and post generation depends on the summaries produced in step 1.

    On failure of either LLM call:
      - Appends to ctx.errors
      - Sets ctx.used_fallback = True
      - Falls back to a minimal non-LLM draft so the pipeline continues

    Writes ctx.summarized_items and ctx.posts_markdown.
    """

    @property
    def name(self) -> str:
        return "ContentAgent"

    def run(self, ctx: AgentContext) -> AgentContext:
        if not ctx.ranked_items:
            self._log(ctx, "warning", "No ranked items — skipping content generation")
            ctx.posts_markdown = "No new high-relevance items found today."
            ctx.should_continue = False
            return ctx

        max_posts = ctx.config.selection.max_posts
        self._log(ctx, "info", "Summarizing %d items", len(ctx.ranked_items))

        # Step 1: Summarize — extract structured bullets and why_it_matters
        try:
            ctx.summarized_items = summarize_items(ctx.ranked_items)
            self._log(ctx, "info", "Summarized %d items", len(ctx.summarized_items))
        except Exception as exc:
            err = f"summarize_items failed: {exc}"
            self._log(ctx, "exception", err)
            ctx.errors.append(err)
            ctx.summarized_items = ctx.ranked_items  # passthrough without bullets
            ctx.used_fallback = True

        if ctx.debug_mode:
            self._log(ctx, "debug", "─── Summaries ───")
            for i, item in enumerate(ctx.summarized_items, 1):
                bullets = "\n          ".join(item.summary_bullets) if item.summary_bullets else "(none)"
                self._log(
                    ctx, "debug",
                    "  [%d] %s\n        why: %s\n        reflection: %s\n        bullets:\n          %s",
                    i, item.title[:80],
                    (item.why_it_matters or "(missing)")[:120],
                    (item.reflection or "(missing)")[:120],
                    bullets,
                )

        # Step 2: Generate posts — LinkedIn draft per summarized item
        self._log(ctx, "info", "Generating up to %d LinkedIn post drafts", max_posts)
        try:
            ctx.posts_markdown = generate_posts(ctx.summarized_items, max_posts=max_posts)
            self._log(ctx, "info", "Posts generated (%d chars)", len(ctx.posts_markdown))
        except Exception as exc:
            err = f"generate_posts failed: {exc}"
            self._log(ctx, "exception", err)
            ctx.errors.append(err)
            ctx.posts_markdown = _fallback_posts(ctx.summarized_items)
            ctx.used_fallback = True

        if ctx.debug_mode:
            self._log(ctx, "debug", "─── Generated posts (first 500 chars) ───")
            self._log(ctx, "debug", "%s", ctx.posts_markdown[:500])

        return ctx
