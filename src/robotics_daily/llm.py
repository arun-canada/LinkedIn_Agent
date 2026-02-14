from __future__ import annotations

import json
import os
from typing import Any

import requests

from .models import SourceItem


OPENAI_URL = "https://api.openai.com/v1/responses"
MODEL = "gpt-4.1-mini"


def _call_openai(input_messages: list[dict[str, Any]]) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required")

    payload = {"model": MODEL, "input": input_messages}
    response = requests.post(
        OPENAI_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=45,
    )
    response.raise_for_status()
    data = response.json()
    return data.get("output_text", "").strip()


def summarize_items(items: list[SourceItem]) -> list[SourceItem]:
    summarized: list[SourceItem] = []
    for item in items:
        prompt = (
            "Summarize this source into JSON with fields bullets (2-3 bullet strings) and why_it_matters (string). "
            "Avoid precise numbers if uncertain.\n\n"
            f"Title: {item.title}\nURL: {item.url}\nDate: {item.published_at.isoformat()}\n"
            f"Text:\n{item.raw_text_excerpt[:4000]}"
        )
        out = _call_openai(
            [
                {
                    "role": "system",
                    "content": "You are a technical writer for autonomy & robotics. Write accurate, non-hyped summaries.",
                },
                {"role": "user", "content": prompt},
            ]
        )
        try:
            parsed = json.loads(out)
            item.summary_bullets = [str(x) for x in parsed.get("bullets", [])][:3]
            item.why_it_matters = str(parsed.get("why_it_matters", "")).strip()
        except Exception:
            item.summary_bullets = ["Key update captured from source."]
            item.why_it_matters = "Potential relevance for simulation, automation, or validation workflows."
        summarized.append(item)
    return summarized


def generate_posts(items: list[SourceItem], max_posts: int = 3) -> str:
    serial = []
    for i, item in enumerate(items, start=1):
        serial.append(
            {
                "idx": i,
                "title": item.title,
                "url": item.url,
                "date": item.published_at.date().isoformat(),
                "bullets": item.summary_bullets,
                "why_it_matters": item.why_it_matters,
            }
        )

    prompt = (
        f"Create {max_posts} LinkedIn-style social media post drafts in markdown. "
        "Focus on autonomy + robotics with strong relevance to simulation, automation, validation. "
        "Include source links in each draft. Avoid hype and avoid precise numeric claims when uncertain. "
        "Separate each draft with '\n\n---\n\n'.\n"
        f"Sources:\n{json.dumps(serial, indent=2)}"
    )
    return _call_openai(
        [
            {
                "role": "system",
                "content": "You are a technical writer for autonomy & robotics. Write accurate, non-hyped posts.",
            },
            {"role": "user", "content": prompt},
        ]
    )
