from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables before importing modules that use requests
# override=True ensures .env values take precedence over system variables
load_dotenv(override=True)

from .config import load_config
from .dedupe import CacheDB, canonicalize_url, content_hash
from .extract import enrich_source_excerpt
from .llm import generate_posts, summarize_items
from .render import write_outputs
from .rss import fetch_rss_sources
from .scoring import rank_items
from .yahoo_imap import safe_fetch_newsletter_links


def setup_logging() -> None:
    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        handlers=[logging.FileHandler("logs/app.log", encoding="utf-8"), logging.StreamHandler()],
    )




def _fallback_posts(items):
    chunks = ["## Draft 1\n", "Quick roundup from today in autonomy + robotics focused on simulation, automation, and validation:\n"]
    for i, item in enumerate(items[:6], start=1):
        chunks.append(f"- {item.title} ({item.url})")
    chunks.append("\n#Robotics #Autonomy #Simulation #Automation #Validation")
    return "\n".join(chunks)

def run_command(config_path: str) -> int:
    setup_logging()
    logger = logging.getLogger(__name__)

    cfg = load_config(config_path)
    cache = CacheDB("cache.db")

    rss_items = fetch_rss_sources(cfg.rss_feeds)
    mail_items = safe_fetch_newsletter_links(
        cfg.newsletter,
        os.environ.get("YAHOO_EMAIL"),
        os.environ.get("YAHOO_APP_PASSWORD"),
    )
    all_items = rss_items + mail_items
    logger.info("Fetched %d RSS items, %d newsletter-link items", len(rss_items), len(mail_items))

    filtered = []
    for item in all_items:
        canonical = canonicalize_url(item.url)
        excerpt = enrich_source_excerpt(canonical, item.raw_text_excerpt)
        c_hash = content_hash(excerpt or item.title)
        if cache.seen_recently(canonical, c_hash, days=30):
            continue
        item.url = canonical
        item.raw_text_excerpt = excerpt
        filtered.append((item, c_hash))

    ranked = rank_items([i for i, _ in filtered], cfg.topics.primary, cfg.selection.max_items)
    if not ranked:
        logger.warning("No new ranked items found; generating fallback output files.")
        posts_md = "No new high-relevance items found today."
        write_outputs(cfg.output.dir, posts_md, [])
        return 0

    try:
        summarized = summarize_items(ranked)
        posts_md = generate_posts(summarized, max_posts=cfg.selection.max_posts)
    except Exception as exc:
        logger.exception("LLM generation failed, using local fallback draft: %s", exc)
        summarized = ranked
        posts_md = _fallback_posts(summarized)

    posts_path, sources_path = write_outputs(cfg.output.dir, posts_md, summarized)
    print(f"Generated: {posts_path}")
    print(f"Generated: {sources_path}")

    hash_by_url = {i.url: h for i, h in filtered}
    for item in summarized:
        cache.mark_seen(item.url, hash_by_url.get(item.url, content_hash(item.raw_text_excerpt)))

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="robotics_daily", description="Generate daily robotics social drafts")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="Run daily ingestion and draft generation")
    run_p.add_argument("--config", default="config/feeds.yaml", help="Path to feeds config YAML")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "run":
        return run_command(args.config)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
