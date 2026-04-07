from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

from ..models import SourceItem
from .base import AgentContext, BaseAgent


# ---------------------------------------------------------------------------
# Pure scoring helpers (no domain-specific knowledge)
# ---------------------------------------------------------------------------

def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except ValueError:
        return ""


def _has(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text, flags=re.IGNORECASE))


def _count(patterns: list[str], text: str) -> int:
    return sum(1 for p in patterns if _has(p, text))


def _count_keywords(text: str, kws: list[str]) -> int:
    score = 0
    for kw in kws:
        kw = kw.strip().lower()
        if not kw:
            continue
        if re.search(rf"\b{re.escape(kw)}\b", text):
            score += 1
    return score


def _freshness(published_at: datetime | None, half_life_days: float = 5.0) -> float:
    if not published_at:
        return 0.25
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (datetime.now(timezone.utc) - published_at).total_seconds() / 86400.0)
    return math.exp(-math.log(2) * (age_days / half_life_days))


def _authority(domain: str, trust_map: dict[str, float]) -> float:
    if not domain:
        return trust_map.get("default", 0.45)
    if domain in trust_map:
        return trust_map[domain]
    for k, v in trust_map.items():
        if k != "default" and (domain == k or domain.endswith("." + k)):
            return v
    return trust_map.get("default", 0.45)


def pick_top_with_diversity(
    scored: list[tuple[float, SourceItem, dict]],
    max_items: int,
    per_domain: int = 2,
) -> list[SourceItem]:
    picked = []
    counts = defaultdict(int)
    for s, item, breakdown in sorted(scored, key=lambda x: x[0], reverse=True):
        dom = breakdown.get("domain") or _domain(item.url)
        if counts[dom] >= per_domain:
            continue
        picked.append(item)
        item.score = s
        counts[dom] += 1
        if len(picked) >= max_items:
            break
    return picked


@dataclass
class ScoringConfig:
    """All domain-specific scoring constants in one place.

    Default values are tuned for robotics/autonomy content.
    To adapt for a different domain, pass a custom ScoringConfig:

        cybersec = ScoringAgent(ScoringConfig(
            anchor_keywords=["vulnerability", "cve", "exploit"],
            pillars={"offensive": [...], "defensive": [...], "compliance": [...]},
            trust_map={"nvd.nist.gov": 0.95, "krebsonsecurity.com": 0.90, "default": 0.40},
            weight_relevance=3.5,
            validation_pillar_name="compliance",
        ))
        top_items = cybersec.score_and_rank(items, max_items=10)
    """

    # Core topic keywords — used to compute the relevance signal
    anchor_keywords: list[str] = field(default_factory=lambda: [
        "robot", "robotics", "autonomy", "autonomous", "self-driving",
        "slam", "lidar", "sensor fusion", "planning", "perception", "localization",
    ])

    # Thematic pillars: topic name → list of keywords
    pillars: dict[str, list[str]] = field(default_factory=lambda: {
        "simulation": ["simulation", "simulator", "digital twin", "synthetic data",
                       "gazebo", "isaac sim", "scenario"],
        "validation": ["validation", "verification", "verify", "testing", "test",
                       "safety", "iso 26262", "sotif", "coverage"],
        "edge_ai": ["edge", "jetson", "tensorrt", "quantization", "onnx",
                    "latency", "runtime", "deployment", "real-time"],
        "ai": ["foundation model", "transformer", "diffusion", "llm", "vlm",
               "imitation", "reinforcement learning", "policy"],
    })

    # Domain authority scores; "default" is the fallback for unknown domains
    trust_map: dict[str, float] = field(default_factory=lambda: {
        "blogs.nvidia.com": 0.95,
        "developer.nvidia.com": 0.95,
        "nvidia.com": 0.90,
        "spectrum.ieee.org": 0.95,
        "ieee.org": 0.90,
        "arxiv.org": 0.90,
        "therobotreport.com": 0.85,
        "ros.org": 0.85,
        "openrobotics.org": 0.85,
        "research.google": 0.90,
        "aws.amazon.com": 0.85,
        "microsoft.com": 0.80,
        "robohub.org": 0.75,
        "github.com": 0.70,
        "gitlab.com": 0.70,
        "default": 0.45,
    })

    # Regex patterns for hype words (penalised in scoring)
    hype_patterns: list[str] = field(default_factory=lambda: [
        r"\bgame[- ]changing\b", r"\brevolutionary\b", r"\bbreakthrough\b",
        r"\bunprecedented\b", r"\bworld['']s first\b", r"\bdisrupt(ive|ing)?\b",
        r"\bnext[- ]gen\b",
    ])

    # Regex patterns that indicate concrete evidence (rewarded in scoring)
    evidence_patterns: list[str] = field(default_factory=lambda: [
        r"github\.com/", r"gitlab\.com/", r"arxiv\.org/", r"\bdoi:\s*\S+",
        r"\bopen[- ]source\b", r"\bdataset\b", r"\bbenchmark\b", r"\bevaluation\b",
        r"\bmetrics?\b", r"\b(latency|throughput|fps|hz|ms)\b",
        r"\biso\s*26262\b", r"\bsotif\b", r"\bopen\s*scenario\b|\bopenscenario\b",
    ])

    # Regex patterns that signal social shareability (rewarded)
    social_patterns: list[str] = field(default_factory=lambda: [
        r"\breleased\b|\blaunch(ed)?\b",
        r"\bnew\b.*\b(tool|framework|library|dataset|benchmark)\b",
        r"\bopen[- ]source\b",
        r"\btutorial\b|\bhow[- ]to\b",
        r"\bcase study\b|\bpostmortem\b",
        r"\bproduction\b|\bdeployed\b|\bin the wild\b",
        r"\bdemo\b|\bvideo\b",
    ])

    # Score formula weights (all signals normalized to [0, 1])
    weight_relevance: float = 3.5
    weight_freshness: float = 1.4
    weight_authority: float = 1.2
    weight_evidence: float = 1.0
    weight_novelty: float = 0.8
    weight_social: float = 0.6
    weight_depth: float = 0.4
    weight_hype_penalty: float = 1.3
    newsletter_bias: float = 0.0  # zeroed — enrichment normalizes content quality across sources

    # Which pillar gets the extra bonus (domain focus area)
    validation_pillar_name: str | None = "validation"
    validation_pillar_bonus: float = 0.15

    # Diversity: max items from the same domain in the final ranking
    per_domain_cap: int = 2

    # Freshness half-life in days (score halves every N days)
    freshness_half_life_days: float = 5.0


class ScoringAgent(BaseAgent):
    """Domain-configurable scoring and ranking agent.

    Uses ScoringConfig to parameterise all keyword lists, trust maps, and weights.
    All signals are normalized to [0, 1] for predictable score ranges.

    Public API beyond run():
        score_and_rank(items, max_items) → list[SourceItem]
            Standalone method; call it without a pipeline for batch scoring.
    """

    def __init__(self, scoring_config: ScoringConfig | None = None) -> None:
        self._cfg = scoring_config or ScoringConfig()

    @property
    def name(self) -> str:
        return "ScoringAgent"

    def run(self, ctx: AgentContext) -> AgentContext:
        if not ctx.validated_items:
            self._log(ctx, "warning", "No validated items to score")
            ctx.ranked_items = []
            return ctx

        max_items = ctx.config.selection.max_items
        self._log(ctx, "info", "Scoring %d items (selecting top %d)", len(ctx.validated_items), max_items)

        ctx.ranked_items = self.score_and_rank(ctx.validated_items, max_items,
                                               debug=ctx.debug_mode, agent=self, agent_ctx=ctx)
        self._log(ctx, "info", "Ranked to %d items after diversity filter", len(ctx.ranked_items))

        if ctx.debug_mode:
            self._log(ctx, "debug", "─── Final ranked items ───")
            for i, item in enumerate(ctx.ranked_items, 1):
                self._log(ctx, "debug", "  [%d] score=%.2f  %s", i, item.score, item.title[:80])

        if ctx.ranked_items:
            top = ctx.ranked_items[0]
            self._log(ctx, "info", "Top item: '%s' (score=%.2f)", top.title[:70], top.score)

        return ctx

    def score_and_rank(
        self,
        items: list[SourceItem],
        max_items: int,
        *,
        debug: bool = False,
        agent: "ScoringAgent | None" = None,
        agent_ctx: "AgentContext | None" = None,
    ) -> list[SourceItem]:
        """Score and rank items. Callable without a pipeline — the reusable entry point."""
        scored = [
            (score, item, breakdown)
            for item in items
            for score, breakdown in [self._score_item(item)]
        ]

        if debug and agent is not None and agent_ctx is not None:
            agent._log(agent_ctx, "debug", "─── Per-item scores (before diversity filter) ───")
            for score, item, bd in sorted(scored, key=lambda x: x[0], reverse=True):
                agent._log(
                    agent_ctx, "debug",
                    "  score=%5.2f  rel=%.2f  fresh=%.2f  auth=%.2f  "
                    "evid=%.2f  nov=%.2f  soc=%.2f  depth=%.2f  hype=%.2f  | %s",
                    score,
                    bd["relevance"], bd["freshness"], bd["authority"],
                    bd["evidence"], bd["novelty"], bd["social"],
                    bd["depth"], bd["hype_penalty"],
                    item.title[:60],
                )

        return pick_top_with_diversity(scored, max_items, per_domain=self._cfg.per_domain_cap)

    # ------------------------------------------------------------------
    # Private scoring helpers — all read from self._cfg, not module globals
    # ------------------------------------------------------------------

    def _score_item(
        self,
        item: SourceItem,
    ) -> tuple[float, dict]:
        text = f"{item.title}\n{item.raw_text_excerpt}".lower()
        dom = _domain(item.url)
        cfg = self._cfg

        relevance = self._relevance(text)
        freshness = _freshness(item.published_at, cfg.freshness_half_life_days)
        authority = _authority(dom, cfg.trust_map)
        evidence = min(1.0, _count(cfg.evidence_patterns, text) * 0.25)
        video_bonus = 0.2 if any(x in dom for x in ["youtube.com", "youtu.be", "vimeo.com"]) else 0.0
        social = min(1.0, _count(cfg.social_patterns, text) * 0.15 + video_bonus)
        hype = min(1.0, _count(cfg.hype_patterns, text) * 0.4)
        depth = min(1.0, len(item.raw_text_excerpt.strip()) / 1500)

        # Novelty: all items that survived FilterAgent's dedup are novel within this run.
        # Default to 1.0 — FilterAgent already handles title/content dedup.
        novelty = 1.0

        nl_bias = cfg.newsletter_bias if item.source_type == "newsletter_link" else 0.0

        score = (
            cfg.weight_relevance * relevance
            + cfg.weight_freshness * freshness
            + cfg.weight_authority * authority
            + cfg.weight_evidence * evidence
            + cfg.weight_novelty * novelty
            + cfg.weight_social * social
            + cfg.weight_depth * depth
            + nl_bias
            - cfg.weight_hype_penalty * hype
        )

        item.score = score

        return score, {
            "domain": dom,
            "relevance": relevance,
            "freshness": freshness,
            "authority": authority,
            "evidence": evidence,
            "novelty": novelty,
            "social": social,
            "depth": depth,
            "hype_penalty": hype,
            "newsletter_bias": nl_bias,
            "final_score": score,
        }

    def _relevance(self, text: str) -> float:
        cfg = self._cfg
        robotics = min(_count_keywords(text, cfg.anchor_keywords), 3)
        pillar_hits = {k: _count_keywords(text, v) for k, v in cfg.pillars.items()}
        active_pillars = sum(1 for p in pillar_hits.values() if p > 0)
        num_pillars = max(1, len(cfg.pillars))

        # Base relevance from anchor keywords and pillar coverage
        rel = (0.3 * robotics + 0.4 * active_pillars) / num_pillars

        # Synergy bonus: scales with match strength, not flat
        if robotics > 0 and active_pillars > 0:
            rel += min(0.4, 0.15 * min(robotics, 2) * active_pillars)

        # Validation pillar bonus (domain focus area)
        if cfg.validation_pillar_name:
            val_hits = pillar_hits.get(cfg.validation_pillar_name, 0)
            rel += cfg.validation_pillar_bonus * min(val_hits, 2)

        return min(1.0, rel)
