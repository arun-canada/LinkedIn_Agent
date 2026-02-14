from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .models import SourceItem


def write_outputs(output_dir: str, posts_markdown: str, sources: list[SourceItem]) -> tuple[Path, Path]:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    posts_path = out_dir / f"{date_str}_posts.md"
    sources_path = out_dir / f"{date_str}_sources.json"

    posts_header = f"# Robotics Daily Drafts ({date_str})\n\n"
    posts_path.write_text(posts_header + posts_markdown.strip() + "\n", encoding="utf-8")

    serializable = []
    for item in sources:
        d = asdict(item)
        d["published_at"] = item.published_at.isoformat()
        serializable.append(d)
    sources_path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")

    return posts_path, sources_path
