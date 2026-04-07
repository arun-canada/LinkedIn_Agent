from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env before importing any module that reads environment variables
load_dotenv(override=True)

from .agents import (
    AgentContext,
    ContentAgent,
    FilterAgent,
    IngestionAgent,
    Pipeline,
    ReviewAgent,
    ScoringAgent,
    StepConfig,
)
from .config import load_config
from .dedupe import CacheDB
from .render import write_outputs
from .notify import format_top_recommendations, generate_pdf, send_document, send_message
from .bot import serve as _bot_serve


def setup_logging(debug: bool = False) -> None:
    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        handlers=[
            logging.FileHandler("logs/app.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def run_command(
    config_path: str,
    debug: bool = False,
    notify: bool = False,
    top_n: int = 2,
    send_pdf: bool = False,
) -> int:
    setup_logging(debug=debug)

    cfg = load_config(config_path)
    ctx = AgentContext(
        config=cfg,
        cache=CacheDB("cache.db"),
        output_dir=cfg.output.dir,
        yahoo_email=os.environ.get("YAHOO_EMAIL"),
        yahoo_password=os.environ.get("YAHOO_APP_PASSWORD"),
        debug_mode=debug,
    )

    pipeline = Pipeline([
        StepConfig(IngestionAgent(), critical=True),
        FilterAgent(),
        ScoringAgent(),
        ContentAgent(),
        ReviewAgent(),
    ])
    ctx = pipeline.run(ctx)

    posts_path, sources_path = write_outputs(
        cfg.output.dir,
        ctx.posts_markdown or "No new high-relevance items found today.",
        ctx.summarized_items or [],
        ctx.recommendations,
    )
    print(f"Generated: {posts_path}")
    print(f"Generated: {sources_path}")

    if ctx.errors:
        for err in ctx.errors:
            print(f"[WARNING] {err}")

    if notify:
        _notify(ctx, posts_path, top_n=top_n, send_pdf=send_pdf)

    return 0


def _notify(ctx, posts_path, *, top_n: int, send_pdf: bool) -> None:
    log = logging.getLogger("robotics_daily")
    try:
        if send_pdf:
            pdf_path = posts_path.with_suffix(".pdf")
            generate_pdf(
                ctx.posts_markdown or "",
                ctx.recommendations or [],
                pdf_path,
            )
            send_document(pdf_path, caption=f"Robotics Daily — {pdf_path.stem}")
            log.info("Sent PDF via Telegram: %s", pdf_path.name)
        else:
            text = format_top_recommendations(
                ctx.recommendations or [],
                ctx.summarized_items or [],
                top_n=top_n,
            )
            send_message(text)
            log.info("Sent top-%d recommendations via Telegram", top_n)
    except Exception as exc:
        log.error("Telegram notification failed: %s", exc)
        print(f"[WARNING] Telegram notification failed: {exc}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="robotics_daily", description="Generate daily robotics social drafts")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="Run daily ingestion and draft generation")
    run_p.add_argument("--config", default="config/feeds.yaml", help="Path to feeds config YAML")
    run_p.add_argument("--debug", action="store_true",
                       help="Enable per-item debug logging for each pipeline stage")

    notify_group = run_p.add_argument_group("Telegram notifications")
    notify_group.add_argument("--notify", action="store_true",
                              help="Send results to your phone via Telegram after the run")
    mode = notify_group.add_mutually_exclusive_group()
    mode.add_argument("--top", type=int, default=2, metavar="N",
                      help="Send top N recommendations as a text message (default: 2)")
    mode.add_argument("--pdf", action="store_true",
                      help="Send all posts as a PDF instead of a text message")

    serve_p = sub.add_parser("serve", help="Start Telegram bot — trigger runs by messaging the bot")
    serve_p.add_argument("--config", default="config/feeds.yaml", help="Path to feeds config YAML")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "run":
        return run_command(
            args.config,
            debug=args.debug,
            notify=args.notify,
            top_n=args.top,
            send_pdf=args.pdf,
        )
    if args.command == "serve":
        setup_logging()
        _bot_serve(config_path=args.config)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
