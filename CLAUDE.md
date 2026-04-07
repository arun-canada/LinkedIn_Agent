# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**robotics_daily** — A CLI agent that monitors robotics/autonomy news from RSS feeds and email newsletters, scores items for relevance, and generates LinkedIn post drafts using an LLM.

## Commands

```bash
# Install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .

# Run the pipeline
python -m robotics_daily.cli run [--config config/feeds.yaml] [--debug] [--notify] [--top N] [--pdf]

# Start Telegram bot for remote triggering
python -m robotics_daily.cli serve

# Tests
pytest -q                          # runs tests/test_dedupe.py
```

## Architecture

Five agents execute sequentially via a `Pipeline`, each mutating a shared `AgentContext` dataclass:

1. **IngestionAgent** — Fetches RSS feeds (feedparser) and Yahoo IMAP newsletters in parallel → `ctx.raw_items`
2. **FilterAgent** — Junk URL regex, trivial excerpt filter, within-run dedup, 30-day SQLite cache dedup, then enriches via trafilatura → `ctx.validated_items`
3. **ScoringAgent** — Multi-signal scoring (relevance, freshness, authority, evidence, novelty, social, hype penalty) with diversity cap (max 2/domain) → `ctx.ranked_items`
4. **ContentAgent** — Two LLM calls per item: summarize (JSON bullets + why_it_matters) then generate LinkedIn post → `ctx.summarized_items`, `ctx.posts_markdown`
5. **ReviewAgent** — Classifies items as publish/review/skip based on score thresholds (6.0/4.0), downgrades all to "review" on LLM fallback, flushes cache → `ctx.recommendations`

Agents inherit `BaseAgent` (`agents/base.py`). Pipeline (`agents/pipeline.py`) supports `StepConfig(critical=True)` to abort on failure, and agents can set `ctx.should_continue = False` to stop early. Non-fatal errors go to `ctx.errors`.

## Key Design Patterns

- **ScoringConfig** is a dataclass parameterizing all scoring keywords, trust maps, and weights — designed to be reusable for other domains beyond robotics.
- **LLM abstraction** (`llm.py`) supports OpenAI API or local models (Ollama/LM Studio) via OpenAI-compatible endpoint. Falls back to static drafts on failure.
- **Dedup** (`dedupe.py`) canonicalizes URLs (strips tracking params) and stores both URL and content hash in SQLite for cross-run dedup over 30 days.
- **Telegram bot** (`bot.py`) uses long-polling (no webhook, no FastAPI dependency).

## Configuration

- `config/feeds.yaml` — RSS feed URLs, newsletter IMAP settings, selection limits, output dir
- `.env` — Credentials: `LLM_PROVIDER`, `OPENAI_API_KEY`/`OPENAI_MODEL` or `LOCAL_MODEL`/`LOCAL_BASE_URL`, `YAHOO_EMAIL`/`YAHOO_APP_PASSWORD`, `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`
- Config models validated via Pydantic (`config.py`)

## Output

- `output/YYYY-MM-DD_posts.md` — LinkedIn drafts + quality review table
- `output/YYYY-MM-DD_sources.json` — Full scored metadata
- `cache.db` — SQLite dedup cache
- `logs/app.log` — Execution logs
