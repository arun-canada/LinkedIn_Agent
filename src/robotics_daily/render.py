from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import PostRecommendation, SourceItem

_FLAG_ICONS = {
    "publish": "✅ publish",
    "review": "⚠️ review",
    "skip": "❌ skip",
}


def _format_recommendations(recs: list[PostRecommendation]) -> str:
    if not recs:
        return ""

    lines = [
        "\n\n---\n",
        "## Review Agent Recommendations\n",
        "| # | Title | Score | Flag | Reason |",
        "|---|-------|-------|------|--------|",
    ]
    for rec in recs:
        title_link = f"[{rec.item_title[:60]}]({rec.item_url})"
        flag = _FLAG_ICONS.get(rec.quality_flag, rec.quality_flag)
        lines.append(
            f"| {rec.post_index} | {title_link} | {rec.item_score:.2f} "
            f"| {flag} | {rec.reason} |"
        )

    publish_count = sum(1 for r in recs if r.quality_flag == "publish")
    review_count = sum(1 for r in recs if r.quality_flag == "review")
    skip_count = sum(1 for r in recs if r.quality_flag == "skip")
    lines.append(
        f"\n**Summary:** {publish_count} ready to publish, "
        f"{review_count} need review, {skip_count} skipped."
    )
    return "\n".join(lines)


def write_outputs(
    output_dir: str,
    posts_markdown: str,
    sources: list[SourceItem],
    recommendations: Optional[list[PostRecommendation]] = None,
) -> tuple[Path, Path]:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    posts_path = out_dir / f"{date_str}_posts.md"
    sources_path = out_dir / f"{date_str}_sources.json"

    supervisor_section = _format_recommendations(recommendations or [])
    posts_header = f"# Robotics Daily Drafts ({date_str})\n\n"
    posts_path.write_text(
        posts_header + posts_markdown.strip() + supervisor_section + "\n",
        encoding="utf-8",
    )

    serializable = []
    for item in sources:
        d = asdict(item)
        d["published_at"] = item.published_at.isoformat()
        serializable.append(d)
    sources_path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")

    return posts_path, sources_path
