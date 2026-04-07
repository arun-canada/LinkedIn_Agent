"""Telegram bot server — long-polling, no extra dependencies beyond requests.

Commands accepted (send these to the bot from your phone):
  /run          run pipeline, send top 2 recommendations
  /run top 5    run pipeline, send top 5 recommendations
  /run pdf      run pipeline, send full posts as PDF
  /help         show available commands
  /status       show bot is alive
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from .notify import get_bot_token, get_chat_id, send_document, send_message, telegram_post

log = logging.getLogger("robotics_daily.bot")


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def _run_pipeline(top_n: int = 2, send_pdf: bool = False, config_path: str = "config/feeds.yaml") -> None:
    """Import and run the pipeline, then send results via Telegram."""
    from .cli import run_command
    run_command(config_path, notify=True, top_n=top_n, send_pdf=send_pdf)


# ---------------------------------------------------------------------------
# Command parser
# ---------------------------------------------------------------------------

HELP_TEXT = (
    "*Robotics Daily Bot*\n\n"
    "Commands:\n"
    "  /run — run pipeline, send top 2 picks\n"
    "  /run top N — send top N picks (e.g. /run top 5)\n"
    "  /run pdf — send full posts as PDF\n"
    "  /status — check bot is alive\n"
    "  /help — show this message"
)


def _handle(text: str) -> None:
    text = text.strip()
    log.info("Received: %s", text)

    if text in ("/help", "/help@robotics_daily_bot"):
        send_message(HELP_TEXT)
        return

    if text.startswith("/status"):
        send_message("✅ Bot is running.")
        return

    if text.startswith("/run"):
        parts = text.split()
        send_pdf = "pdf" in parts
        top_n = 2
        if "top" in parts:
            try:
                top_n = int(parts[parts.index("top") + 1])
            except (IndexError, ValueError):
                top_n = 2

        mode = "PDF" if send_pdf else f"top {top_n} picks"
        send_message(f"⏳ Running pipeline... will send {mode} when done.")
        try:
            _run_pipeline(top_n=top_n, send_pdf=send_pdf)
        except Exception as exc:
            log.exception("Pipeline error")
            send_message(f"❌ Pipeline failed: {exc}")
        return

    send_message("Unknown command. Send /help to see available commands.")


# ---------------------------------------------------------------------------
# Long-polling loop
# ---------------------------------------------------------------------------

def serve(config_path: str = "config/feeds.yaml") -> None:
    """Start the bot. Blocks forever, polling Telegram for new messages."""
    log.info("Bot starting — polling for messages...")
    send_message("🤖 Robotics Daily bot started. Send /help for commands.")

    offset = 0
    while True:
        try:
            data = telegram_post("getUpdates", json={"offset": offset, "timeout": 30, "allowed_updates": ["message"]})
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                text = msg.get("text", "")
                sender_id = str(msg.get("chat", {}).get("id", ""))

                # Only respond to the configured chat (basic auth)
                if sender_id != get_chat_id():
                    log.warning("Ignored message from unknown chat_id: %s", sender_id)
                    continue

                if text:
                    _handle(text)

        except KeyboardInterrupt:
            log.info("Bot stopped.")
            break
        except Exception as exc:
            log.error("Polling error: %s — retrying in 5s", exc)
            time.sleep(5)
