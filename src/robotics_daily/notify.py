from __future__ import annotations

import os
import re
import textwrap
from datetime import datetime
from pathlib import Path

import requests

from .models import PostRecommendation, SourceItem


# ---------------------------------------------------------------------------
# Telegram helpers
# ---------------------------------------------------------------------------

def get_bot_token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set in .env\n"
            "Create a bot via @BotFather on Telegram, then set TELEGRAM_BOT_TOKEN."
        )
    return token


def get_chat_id() -> str:
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not chat_id:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID is not set in .env\n"
            "Send a message to your bot then visit: "
            "https://api.telegram.org/bot<TOKEN>/getUpdates to find your chat_id."
        )
    return chat_id


def telegram_post(method: str, **kwargs) -> dict:
    token = get_bot_token()
    url = f"https://api.telegram.org/bot{token}/{method}"
    resp = requests.post(url, timeout=30, **kwargs)
    resp.raise_for_status()
    return resp.json()


def send_message(text: str) -> None:
    """Send a Markdown-formatted message to the configured Telegram chat."""
    telegram_post(
        "sendMessage",
        json={"chat_id": get_chat_id(), "text": text, "parse_mode": "Markdown"},
    )


def send_document(file_path: Path, caption: str = "") -> None:
    """Send a file to the configured Telegram chat."""
    with open(file_path, "rb") as fh:
        telegram_post(
            "sendDocument",
            data={"chat_id": get_chat_id(), "caption": caption},
            files={"document": fh},
        )


# ---------------------------------------------------------------------------
# Message formatter — top N recommendations
# ---------------------------------------------------------------------------

def format_top_recommendations(
    recs: list[PostRecommendation],
    items: list[SourceItem],
    top_n: int = 2,
) -> str:
    """Return a Telegram Markdown string for the top N publish/review items."""
    # publish items first, then review; skip "skip"
    ordered = [r for r in recs if r.quality_flag == "publish"] + [
        r for r in recs if r.quality_flag == "review"
    ]
    top = ordered[:top_n]

    if not top:
        return f"*Robotics Daily — {datetime.now().strftime('%Y-%m-%d')}*\n\nNo recommendations today."

    item_by_url = {it.url: it for it in items}
    lines: list[str] = [f"*Robotics Daily — {datetime.now().strftime('%Y-%m-%d')}*\n"]

    for i, rec in enumerate(top, 1):
        flag_icon = "✅" if rec.quality_flag == "publish" else "⚠️"
        lines.append(f"{flag_icon} *{i}\\. {_escape_md(rec.item_title[:80])}*")
        lines.append(f"Score: {rec.item_score:.2f}")

        item = item_by_url.get(rec.item_url)
        if item and item.why_it_matters:
            lines.append(f"_{_escape_md(item.why_it_matters)}_")
        if item and item.reflection:
            lines.append(f"*My take:* {_escape_md(item.reflection)}")
        if item and item.summary_bullets:
            for bullet in item.summary_bullets[:3]:
                lines.append(f"• {_escape_md(bullet)}")

        lines.append(f"[Read more]({rec.item_url})")
        lines.append("")

    return "\n".join(lines)


def _escape_md(text: str) -> str:
    """Escape characters that have special meaning in Telegram Markdown v1."""
    # Telegram MarkdownV1 treats _ * ` [ as special
    return re.sub(r"([_*`\[])", r"\\\1", text)


# ---------------------------------------------------------------------------
# PDF generator — full posts + recommendations table
# ---------------------------------------------------------------------------

def generate_pdf(
    posts_markdown: str,
    recs: list[PostRecommendation],
    output_path: Path,
) -> Path:
    """Render posts_markdown + recommendations table to a PDF file."""
    try:
        from fpdf import FPDF  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "fpdf2 is required for PDF generation.\n"
            "Run: pip install fpdf2"
        ) from exc

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    date_str = datetime.now().strftime("%Y-%m-%d")

    # Title
    pdf.set_font("Helvetica", style="B", size=18)
    pdf.cell(0, 12, f"Robotics Daily — {date_str}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # Recommendations summary table
    if recs:
        pdf.set_font("Helvetica", style="B", size=13)
        pdf.cell(0, 9, "Review Summary", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=10)
        flag_labels = {"publish": "[PUBLISH]", "review": "[REVIEW]", "skip": "[SKIP]"}
        for rec in recs:
            flag = flag_labels.get(rec.quality_flag, "")
            line = f"{flag}  {rec.item_title[:90]}  (score: {rec.item_score:.2f})"
            pdf.multi_cell(0, 6, line)
        pdf.ln(6)

    # Post drafts
    pdf.set_font("Helvetica", style="B", size=13)
    pdf.cell(0, 9, "Post Drafts", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    for line in posts_markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            pdf.set_font("Helvetica", style="B", size=13)
            pdf.multi_cell(0, 8, stripped[2:])
            pdf.set_font("Helvetica", size=10)
        elif stripped.startswith("## "):
            pdf.set_font("Helvetica", style="B", size=11)
            pdf.multi_cell(0, 7, stripped[3:])
            pdf.set_font("Helvetica", size=10)
        elif stripped == "---":
            pdf.ln(2)
            pdf.line(pdf.get_x(), pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
            pdf.ln(4)
        elif stripped:
            # Wrap long lines so they fit the page
            for chunk in textwrap.wrap(stripped, width=110):
                pdf.multi_cell(0, 6, chunk)
        else:
            pdf.ln(3)

    pdf.output(str(output_path))
    return output_path
