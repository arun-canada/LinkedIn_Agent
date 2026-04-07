from datetime import datetime, timezone

from src.robotics_daily.agents.scoring_agent import (
    ScoringAgent,
    ScoringConfig,
    _authority,
    _freshness,
    pick_top_with_diversity,
)
from src.robotics_daily.models import SourceItem


def _make_item(
    title: str = "Test Article",
    url: str = "https://example.com/article",
    excerpt: str = "A" * 200,
    source_type: str = "rss",
    published_at: datetime | None = None,
) -> SourceItem:
    return SourceItem(
        id="test",
        title=title,
        url=url,
        published_at=published_at or datetime.now(timezone.utc),
        source_type=source_type,
        raw_text_excerpt=excerpt,
        origin="test",
    )


class TestRelevance:
    def test_robotics_keywords_score_positive(self) -> None:
        agent = ScoringAgent()
        text = "robotics simulation digital twin sensor fusion validation testing"
        score = agent._relevance(text.lower())
        assert score > 0.0

    def test_no_keywords_score_zero(self) -> None:
        agent = ScoringAgent()
        text = "cooking recipes for delicious pasta dishes"
        score = agent._relevance(text.lower())
        assert score == 0.0

    def test_relevance_normalized_to_unit(self) -> None:
        agent = ScoringAgent()
        # Stuff every keyword in — should still cap at 1.0
        all_kws = " ".join(ScoringConfig().anchor_keywords)
        all_pillars = " ".join(
            kw for words in ScoringConfig().pillars.values() for kw in words
        )
        text = f"{all_kws} {all_pillars}".lower()
        score = agent._relevance(text)
        assert 0.0 <= score <= 1.0

    def test_synergy_scales_with_strength(self) -> None:
        agent = ScoringAgent()
        # Weak: 1 anchor + 1 pillar
        weak = agent._relevance("robot simulation".lower())
        # Strong: multiple anchors + multiple pillars
        strong = agent._relevance(
            "robot robotics autonomous simulation digital twin validation testing".lower()
        )
        assert strong > weak


class TestScoreItem:
    def test_high_relevance_trusted_domain(self) -> None:
        agent = ScoringAgent()
        item = _make_item(
            title="NVIDIA Isaac Sim robotics simulation validation testing",
            url="https://blogs.nvidia.com/robotics-sim",
            excerpt="robotics simulation digital twin sensor fusion validation " * 20,
        )
        score, bd = agent._score_item(item)
        assert score > 3.0
        assert bd["authority"] == 0.95

    def test_hype_penalty_applied(self) -> None:
        agent = ScoringAgent()
        item = _make_item(
            title="Revolutionary game-changing breakthrough in robotics",
            excerpt="This unprecedented disruptive next-gen robot",
        )
        _, bd = agent._score_item(item)
        assert bd["hype_penalty"] > 0.0

    def test_depth_signal(self) -> None:
        agent = ScoringAgent()
        short_item = _make_item(excerpt="robot test " * 5)
        long_item = _make_item(excerpt="robot test " * 200)
        _, short_bd = agent._score_item(short_item)
        _, long_bd = agent._score_item(long_item)
        assert long_bd["depth"] > short_bd["depth"]

    def test_novelty_is_always_one(self) -> None:
        """All items passing FilterAgent dedup should have novelty=1.0."""
        agent = ScoringAgent()
        item = _make_item()
        _, bd = agent._score_item(item)
        assert bd["novelty"] == 1.0


class TestAuthority:
    def test_exact_domain_match(self) -> None:
        trust = {"arxiv.org": 0.90, "default": 0.45}
        assert _authority("arxiv.org", trust) == 0.90

    def test_subdomain_match(self) -> None:
        trust = {"nvidia.com": 0.90, "default": 0.45}
        assert _authority("blogs.nvidia.com", trust) == 0.90

    def test_malicious_subdomain_rejected(self) -> None:
        trust = {"nvidia.com": 0.90, "default": 0.45}
        # Should NOT match — "evil-nvidia.com" doesn't end with ".nvidia.com"
        assert _authority("evil-nvidia.com", trust) == 0.45

    def test_unknown_domain_gets_default(self) -> None:
        trust = {"arxiv.org": 0.90, "default": 0.45}
        assert _authority("randomsite.io", trust) == 0.45


class TestFreshness:
    def test_just_published(self) -> None:
        score = _freshness(datetime.now(timezone.utc))
        assert score > 0.95

    def test_no_date(self) -> None:
        assert _freshness(None) == 0.25


class TestDiversity:
    def test_per_domain_cap(self) -> None:
        items = [
            _make_item(title=f"Article {i}", url=f"https://same.com/article-{i}")
            for i in range(5)
        ]
        scored = [(10.0 - i, item, {"domain": "same.com"}) for i, item in enumerate(items)]
        picked = pick_top_with_diversity(scored, max_items=5, per_domain=2)
        assert len(picked) == 2

    def test_mixed_domains(self) -> None:
        items_a = [
            _make_item(title=f"A{i}", url=f"https://a.com/{i}") for i in range(3)
        ]
        items_b = [
            _make_item(title=f"B{i}", url=f"https://b.com/{i}") for i in range(3)
        ]
        scored = (
            [(10.0 - i, item, {"domain": "a.com"}) for i, item in enumerate(items_a)]
            + [(8.0 - i, item, {"domain": "b.com"}) for i, item in enumerate(items_b)]
        )
        picked = pick_top_with_diversity(scored, max_items=4, per_domain=2)
        domains = [item.url.split("/")[2] for item in picked]
        assert domains.count("a.com") <= 2
        assert domains.count("b.com") <= 2
