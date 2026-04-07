from __future__ import annotations

from dataclasses import dataclass

from ..dedupe import content_hash
from ..models import PostRecommendation, SourceItem
from .base import AgentContext, BaseAgent

# The default fallback text written by ContentAgent when LLM summary parsing fails
_LLM_FALLBACK_WHY = "Potential relevance for simulation, automation, or validation workflows."


@dataclass
class ReviewConfig:
    """Quality thresholds for post recommendations."""
    publish_score_threshold: float = 6.0  # score >= threshold AND good summary → publish
    review_score_threshold: float = 4.0   # threshold <= score < publish_threshold → review
    # score < review_score_threshold → skip


class ReviewAgent(BaseAgent):
    """Evaluates the quality of each generated post and produces a recommendations table.

    Does NOT orchestrate other agents — purely an evaluator.

    Quality flags:
      publish  score >= 6.0, summary complete (≥2 bullets, why_it_matters filled)
      review   score >= 4.0, or summary incomplete despite high score
      skip     score < 4.0

    If ctx.used_fallback is True, all "publish" flags are downgraded to "review"
    because the LLM output may be lower quality.

    Also flushes the cache: marks all summarized items as seen so they are not
    re-processed on the next run.

    Writes ctx.recommendations.
    """

    def __init__(self, review_config: ReviewConfig | None = None) -> None:
        self._cfg = review_config or ReviewConfig()

    @property
    def name(self) -> str:
        return "ReviewAgent"

    def run(self, ctx: AgentContext) -> AgentContext:
        items = ctx.summarized_items or ctx.ranked_items
        if not items:
            self._log(ctx, "warning", "No items to review")
            return ctx

        ctx.recommendations = self._evaluate(items, ctx)
        self._flush_cache(items, ctx)

        publish = sum(1 for r in ctx.recommendations if r.quality_flag == "publish")
        review = sum(1 for r in ctx.recommendations if r.quality_flag == "review")
        skip = sum(1 for r in ctx.recommendations if r.quality_flag == "skip")
        self._log(
            ctx, "info",
            "Recommendations: %d publish, %d review, %d skip",
            publish, review, skip,
        )

        if ctx.debug_mode:
            self._log(ctx, "debug", "─── Recommendations ───")
            flag_icon = {"publish": "✅", "review": "⚠️", "skip": "❌"}
            for r in ctx.recommendations:
                icon = flag_icon.get(r.quality_flag, "?")
                self._log(
                    ctx, "debug",
                    "  [%d] %s %-8s score=%.2f  %s",
                    r.post_index, icon, r.quality_flag, r.item_score, r.item_title[:70],
                )
                self._log(ctx, "debug", "       reason: %s", r.reason)

        return ctx

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def _evaluate(self, items: list[SourceItem], ctx: AgentContext) -> list[PostRecommendation]:
        recs = []
        for idx, item in enumerate(items, start=1):
            flag, reason = self._classify(item)
            recs.append(PostRecommendation(
                item_title=item.title,
                item_url=item.url,
                item_score=item.score,
                quality_flag=flag,
                reason=reason,
                post_index=idx,
            ))

        # Downgrade all "publish" if LLM fallback was used
        if ctx.used_fallback:
            for rec in recs:
                if rec.quality_flag == "publish":
                    rec.quality_flag = "review"
                    rec.reason += " [LLM fallback used — verify quality]"

        return recs

    def _classify(self, item: SourceItem) -> tuple[str, str]:
        score = item.score
        cfg = self._cfg

        summary_complete = (
            len(item.summary_bullets) >= 2
            and bool(item.why_it_matters)
            and item.why_it_matters.strip() != _LLM_FALLBACK_WHY
            and bool(item.reflection)
        )

        if score < cfg.review_score_threshold:
            return "skip", f"Low relevance score ({score:.2f})"

        if score >= cfg.publish_score_threshold:
            if summary_complete:
                return "publish", f"Strong score ({score:.2f}), well-summarized"
            return "review", (
                f"Strong score ({score:.2f}) but summary incomplete "
                f"(bullets={len(item.summary_bullets)}, "
                f"why_it_matters={'present' if item.why_it_matters else 'missing'})"
            )

        # review_score_threshold <= score < publish_score_threshold
        return "review", f"Moderate score ({score:.2f}); verify before posting"

    # ------------------------------------------------------------------
    # Cache flush
    # ------------------------------------------------------------------

    def _flush_cache(self, items: list[SourceItem], ctx: AgentContext) -> None:
        for item in items:
            fallback = content_hash(item.raw_text_excerpt or item.title)
            c_hash = ctx.url_to_hash.get(item.url, fallback)
            try:
                ctx.cache.mark_seen(item.url, c_hash)
            except OSError as exc:
                self._log(ctx, "warning", "Cache write failed for %s: %s", item.url, exc)
