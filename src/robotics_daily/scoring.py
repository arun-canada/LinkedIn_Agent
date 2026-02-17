from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import urlparse

from .models import SourceItem

HYPE_PATTERNS = [
    r"\bgame[- ]changing\b", r"\brevolutionary\b", r"\bbreakthrough\b",
    r"\bunprecedented\b", r"\bworld['']s first\b", r"\bdisrupt(ive|ing)?\b",
    r"\bnext[- ]gen\b",
]

EVIDENCE_PATTERNS = [
    r"github\.com/", r"gitlab\.com/", r"arxiv\.org/", r"\bdoi:\s*\S+",
    r"\bopen[- ]source\b", r"\bdataset\b", r"\bbenchmark\b", r"\bevaluation\b",
    r"\bmetrics?\b", r"\b(latency|throughput|fps|hz|ms)\b",
    r"\bv?\d+\.\d+(\.\d+)?\b",  # version-like
    r"\biso\s*26262\b", r"\bsotif\b", r"\bopen\s*scenario\b|\bopenscenario\b",
]

SOCIAL_PATTERNS = [
    r"\breleased\b|\blaunch(ed)?\b",
    r"\bnew\b.*\b(tool|framework|library|dataset|benchmark)\b",
    r"\bopen[- ]source\b",
    r"\btutorial\b|\bhow[- ]to\b",
    r"\bcase study\b|\bpostmortem\b",
    r"\bproduction\b|\bdeployed\b|\bin the wild\b",
    r"\bdemo\b|\bvideo\b",
]

ROBOTICS_ANCHOR = [
    "robot", "robotics", "autonomy", "autonomous", "self-driving",
    "slam", "lidar", "sensor fusion", "planning", "perception", "localization"
]

PILLARS = {
    "simulation": ["simulation", "simulator", "digital twin", "synthetic data", "gazebo", "isaac sim", "scenario"],
    "validation": ["validation", "verification", "verify", "testing", "test", "safety", "iso 26262", "sotif", "coverage"],
    "edge_ai": ["edge", "jetson", "tensorrt", "quantization", "onnx", "latency", "runtime", "deployment", "real-time"],
    "ai": ["foundation model", "transformer", "diffusion", "llm", "vlm", "imitation", "reinforcement learning", "policy"],
}

# Domain authority mapping - higher scores for trusted robotics/tech sources
TRUST_MAP = {
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
}


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
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
        # word-ish boundaries reduces false hits
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
        if k != "default" and domain.endswith(k):
            return v
    return trust_map.get("default", 0.45)


def _relevance(text: str) -> float:
    t = text.lower()
    robotics = _count_keywords(t, ROBOTICS_ANCHOR)
    pillar_hits = {k: _count_keywords(t, v) for k, v in PILLARS.items()}
    pillar_total = sum(pillar_hits.values())

    rel = 0.25 * robotics + 0.35 * pillar_total
    if robotics > 0 and pillar_total > 0:
        rel += 1.0  # synergy bonus
    rel += 0.4 * pillar_hits["validation"]  # your special focus
    return min(4.0, rel)


def _evidence(text: str) -> float:
    hits = _count(EVIDENCE_PATTERNS, text)
    return min(1.5, hits * 0.35)


def _social(text: str, url: str) -> float:
    hits = _count(SOCIAL_PATTERNS, text)
    dom = _domain(url)
    video_bonus = 0.3 if any(x in dom for x in ["youtube.com", "youtu.be", "vimeo.com"]) else 0.0
    return min(1.2, hits * 0.2 + video_bonus)


def _hype(text: str) -> float:
    hits = _count(HYPE_PATTERNS, text)
    return min(1.3, hits * 0.5)


def score_item(item: SourceItem, trust_map: dict[str, float], recent_title_norms: set[str]) -> tuple[float, dict]:
    text = f"{item.title}\n{item.raw_text_excerpt}".lower()
    dom = _domain(item.url)

    relevance = _relevance(text)
    freshness = _freshness(item.published_at)
    authority = _authority(dom, trust_map)
    evidence = _evidence(text)
    social = _social(text, item.url)
    hype = _hype(text)

    title_norm = re.sub(r"\s+", " ", (item.title or "").strip().lower())
    novelty = 1.0 if title_norm and title_norm not in recent_title_norms else 0.2

    # newsletter bias only helps a bit; don't let it dominate
    newsletter_bias = 0.15 if item.source_type == "newsletter_link" else 0.0

    score = (
        2.2 * relevance +
        1.4 * freshness +
        1.2 * authority +
        1.0 * evidence +
        0.8 * novelty +
        0.6 * social +
        newsletter_bias -
        1.3 * hype
    )

    return score, {
        "domain": dom,
        "relevance": relevance,
        "freshness": freshness,
        "authority": authority,
        "evidence": evidence,
        "novelty": novelty,
        "social": social,
        "hype_penalty": hype,
        "newsletter_bias": newsletter_bias,
        "final_score": score,
    }


def pick_top_with_diversity(scored: list[tuple[float, SourceItem, dict]], max_items: int, per_domain: int = 2) -> list[SourceItem]:
    picked = []
    counts = defaultdict(int)
    for s, item, breakdown in sorted(scored, key=lambda x: x[0], reverse=True):
        dom = breakdown.get("domain") or _domain(item.url)
        if counts[dom] >= per_domain:
            continue
        picked.append(item)
        item.score = s  # Store score on item
        counts[dom] += 1
        if len(picked) >= max_items:
            break
    return picked


def rank_items(items: list[SourceItem], keywords: list[str], max_items: int) -> list[SourceItem]:
    """
    Rank items using advanced scoring with diversity filtering.

    Args:
        items: List of source items to rank
        keywords: Not used in new scoring (kept for backward compatibility)
        max_items: Maximum number of items to return

    Returns:
        Ranked and diversity-filtered list of items
    """
    # Build set of recent titles for novelty detection
    recent_title_norms = {
        re.sub(r"\s+", " ", (item.title or "").strip().lower())
        for item in items
    }

    # Score all items
    scored = []
    for item in items:
        score, breakdown = score_item(item, TRUST_MAP, recent_title_norms)
        scored.append((score, item, breakdown))

    # Apply diversity filtering and return top items
    return pick_top_with_diversity(scored, max_items, per_domain=2)
