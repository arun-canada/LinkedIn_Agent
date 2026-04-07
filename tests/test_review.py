from datetime import datetime, timezone

from src.robotics_daily.agents.review import ReviewAgent, ReviewConfig
from src.robotics_daily.models import SourceItem


def _make_item(
    score: float = 7.0,
    bullets: list[str] | None = None,
    why: str = "Important for robotics workflows.",
    reflection: str = "This changes how we think about sim-to-real transfer.",
) -> SourceItem:
    item = SourceItem(
        id="test",
        title="Test Article",
        url="https://example.com/article",
        published_at=datetime.now(timezone.utc),
        source_type="rss",
        raw_text_excerpt="Some excerpt text.",
        origin="test",
        score=score,
    )
    item.summary_bullets = bullets if bullets is not None else ["Point one.", "Point two."]
    item.why_it_matters = why
    item.reflection = reflection
    return item


class TestClassify:
    def test_publish_complete_high_score(self) -> None:
        agent = ReviewAgent()
        flag, reason = agent._classify(_make_item(score=7.0))
        assert flag == "publish"
        assert "Strong score" in reason

    def test_review_incomplete_summary(self) -> None:
        agent = ReviewAgent()
        item = _make_item(score=7.0, bullets=["Only one bullet."])
        flag, _ = agent._classify(item)
        assert flag == "review"

    def test_review_missing_why_it_matters(self) -> None:
        agent = ReviewAgent()
        item = _make_item(score=7.0, why="")
        flag, _ = agent._classify(item)
        assert flag == "review"

    def test_review_missing_reflection(self) -> None:
        agent = ReviewAgent()
        item = _make_item(score=7.0, reflection="")
        flag, _ = agent._classify(item)
        assert flag == "review"

    def test_review_moderate_score(self) -> None:
        agent = ReviewAgent()
        flag, reason = agent._classify(_make_item(score=5.0))
        assert flag == "review"
        assert "Moderate" in reason

    def test_skip_low_score(self) -> None:
        agent = ReviewAgent()
        flag, reason = agent._classify(_make_item(score=2.0))
        assert flag == "skip"
        assert "Low" in reason

    def test_review_fallback_why(self) -> None:
        """The LLM fallback why_it_matters string should count as incomplete."""
        agent = ReviewAgent()
        item = _make_item(
            score=7.0,
            why="Potential relevance for simulation, automation, or validation workflows.",
        )
        flag, _ = agent._classify(item)
        assert flag == "review"

    def test_custom_thresholds(self) -> None:
        cfg = ReviewConfig(publish_score_threshold=8.0, review_score_threshold=5.0)
        agent = ReviewAgent(review_config=cfg)
        # Score 7.0 is below custom publish threshold of 8.0
        flag, _ = agent._classify(_make_item(score=7.0))
        assert flag == "review"
        # Score 4.0 is below custom review threshold of 5.0
        flag, _ = agent._classify(_make_item(score=4.0))
        assert flag == "skip"
