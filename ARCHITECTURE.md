# Architecture

## Overview

`robotics_daily` is a **5-agent sequential pipeline**. Each time you run it, agents execute in order, passing a shared context object (`AgentContext`) from one to the next. Each agent has a single responsibility and writes its results back to the context.

```
          ┌──────────────────────────────────────────────────────────┐
          │                    AgentContext                           │
          │  config · cache · raw_items · validated_items ·          │
          │  ranked_items · summarized_items · posts_markdown ·       │
          │  recommendations · errors · should_continue              │
          └──────────────────────────────────────────────────────────┘
                                     │
              ┌──────────────────────┼────────────────────────┐
              ▼                      ▼                         ▼
    ┌──────────────────┐   ┌─────────────────┐   ┌────────────────────┐
    │ IngestionAgent   │   │  FilterAgent     │   │  ScoringAgent      │
    │                  │──▶│                  │──▶│                    │
    │ RSS + Email      │   │ Dedup · Cache ·  │   │ Relevance · Trust  │
    │ → raw_items      │   │ → validated_items│   │ → ranked_items     │
    └──────────────────┘   └─────────────────┘   └────────────────────┘
                                                            │
                           ┌────────────────────────────────┘
                           ▼
             ┌─────────────────────────┐   ┌──────────────────────────┐
             │  ContentAgent           │   │  ReviewAgent              │
             │                         │──▶│                           │
             │  LLM summarize + posts  │   │  Score → publish/review/  │
             │  → summarized_items     │   │  skip · flush cache       │
             │  → posts_markdown       │   │  → recommendations        │
             └─────────────────────────┘   └──────────────────────────┘
```

---

## Pipeline execution

The `Pipeline` class in `agents/pipeline.py` runs agents in sequence. For each step it:

1. Logs `=== AgentName: starting ===`
2. Calls `agent.run(ctx)` and catches any unexpected exceptions
3. Logs timing on success: `=== AgentName: done (3.2s) ===`
4. Checks `ctx.should_continue` — any agent can set this to `False` to stop early (e.g. if nothing was fetched)

```python
# cli.py — the only place the pipeline is assembled
pipeline = Pipeline([
    StepConfig(IngestionAgent(), critical=True),  # abort if this fails
    FilterAgent(),
    ScoringAgent(),
    ContentAgent(),
    ReviewAgent(),
])
ctx = pipeline.run(ctx)
```

Setting `critical=True` on `IngestionAgent` means if it raises an exception, the entire run stops immediately. Other agents swallow errors and append them to `ctx.errors`.

---

## Agent responsibilities

### 1. IngestionAgent (`agents/ingestion.py`)

**Reads:** `ctx.config.rss_feeds`, `ctx.config.newsletter`, credentials
**Writes:** `ctx.raw_items`

Fetches from two external sources in parallel:

- **RSS feeds** via `rss.py` (feedparser) — parses standard RSS/Atom feeds
- **Yahoo IMAP** via `yahoo_imap.py` — connects to Yahoo Mail over IMAP, reads emails from the last `days_back` days, filters by sender allowlist, and extracts individual article links from each newsletter email

Each link or RSS entry becomes a `SourceItem` with: `title`, `url`, `published_at`, `source_type`, `raw_text_excerpt`, `origin`.

**Key detail about newsletters:** The fetcher reads each link's anchor text as the item title (e.g. `"Ai-Da robot pushes art and tech"`), not the email subject line. This means each article in a newsletter email is treated as a distinct item.

---

### 2. FilterAgent (`agents/filter.py`)

**Reads:** `ctx.raw_items`, `ctx.cache`
**Writes:** `ctx.validated_items`, `ctx.url_to_hash`

Four-step filter pipeline (each step logged separately):

| Step | What it drops |
|------|---------------|
| Junk URL filter | Privacy pages, unsubscribe links, Mailchimp signup pages |
| Trivial excerpt | Items with < 30 chars of extracted text |
| Within-run dedup | Duplicate titles or content hashes in the same run |
| Cache dedup | Items already seen within the last 30 days (cross-run) |

Also enriches each surviving item: calls `extract.py` which fetches the full article URL and extracts clean article text using `trafilatura`. This replaces the raw newsletter excerpt with actual article content, which improves scoring accuracy.

If zero items survive all filters, `ctx.should_continue = False` and the pipeline stops.

---

### 3. ScoringAgent (`agents/scoring_agent.py`)

**Reads:** `ctx.validated_items`, `ctx.config.selection.max_items`
**Writes:** `ctx.ranked_items`

Scores each item across 6 signals, then applies diversity filtering:

| Signal | What it measures |
|--------|-----------------|
| **Relevance** | Anchor keyword hits ("robot", "autonomy", etc.) + thematic pillar hits (simulation, validation, edge AI, AI) with synergy bonus |
| **Freshness** | Exponential decay — score halves every 5 days |
| **Authority** | Domain trust score (spectrum.ieee.org = 0.95, unknown = 0.45) |
| **Evidence** | Concrete links (GitHub, arXiv, benchmarks, version numbers) |
| **Novelty** | 1.0 for unique titles, 0.2 for near-duplicates |
| **Social** | Shareability signals (released, open-source, tutorial, demo) |
| **Hype penalty** | Subtracts for "revolutionary", "game-changing", "unprecedented" |

Final score formula:
```
score = 2.2×relevance + 1.4×freshness + 1.2×authority + 1.0×evidence
      + 0.8×novelty + 0.6×social - 1.3×hype_penalty
```

**Diversity filter:** `pick_top_with_diversity()` limits to 2 items per domain, then returns the top `max_items` by score.

**Domain reuse:** The scoring constants live in `ScoringConfig`. You can instantiate `ScoringAgent` with a different config for any content domain:

```python
cybersec = ScoringAgent(ScoringConfig(
    anchor_keywords=["vulnerability", "cve", "exploit"],
    pillars={"offensive": [...], "defensive": [...], "compliance": [...]},
    trust_map={"nvd.nist.gov": 0.95, "default": 0.40},
))
top = cybersec.score_and_rank(items, max_items=10)
```

---

### 4. ContentAgent (`agents/content.py`)

**Reads:** `ctx.ranked_items`, `ctx.config.selection.max_posts`
**Writes:** `ctx.summarized_items`, `ctx.posts_markdown`

Two sequential LLM calls per item:

**Step 1 — Summarize:** For each ranked item, asks the LLM to return JSON with:
- `bullets` — 2-3 key technical points
- `why_it_matters` — one sentence on relevance to autonomy/robotics

**Step 2 — Generate post:** For each summarized item, asks the LLM to write a LinkedIn post draft (2-4 sentences + hashtags) using the bullets and why_it_matters.

If either LLM call fails, the agent falls back to a minimal static draft and sets `ctx.used_fallback = True`, which causes `ReviewAgent` to downgrade any "publish" flags to "review".

**LLM providers** (configured in `.env`):
- `LLM_PROVIDER=openai` — uses OpenAI API with `OPENAI_MODEL`
- `LLM_PROVIDER=local` — uses any OpenAI-compatible local server (Ollama, LM Studio, etc.) via `LOCAL_BASE_URL` and `LOCAL_MODEL`

---

### 5. ReviewAgent (`agents/review.py`)

**Reads:** `ctx.summarized_items`, `ctx.used_fallback`
**Writes:** `ctx.recommendations`

Classifies each post by quality:

| Score | Summary quality | Flag |
|-------|----------------|------|
| ≥ 6.0 | ≥ 2 bullets + why_it_matters filled | ✅ publish |
| ≥ 6.0 | Summary incomplete | ⚠️ review |
| 4.0–6.0 | Any | ⚠️ review |
| < 4.0 | Any | ❌ skip |

If `ctx.used_fallback = True`, all "publish" flags are downgraded to "review".

Also **flushes the cache**: marks all summarized items as seen so they won't be reprocessed on the next run.

---

## Shared context (`AgentContext`)

All agents share one dataclass that flows through the pipeline:

```
AgentContext
├── config          AppConfig loaded from feeds.yaml
├── cache           SQLite CacheDB for dedup
├── output_dir      where to write output files
├── yahoo_email     from environment
├── yahoo_password  from environment
│
├── raw_items       written by IngestionAgent
├── validated_items written by FilterAgent
├── url_to_hash     written by FilterAgent (url → content hash)
├── ranked_items    written by ScoringAgent
├── summarized_items written by ContentAgent
├── posts_markdown  written by ContentAgent
├── used_fallback   written by ContentAgent (True if LLM failed)
├── recommendations written by ReviewAgent
│
├── should_continue set to False to stop pipeline early
├── debug_mode      True if --debug flag passed
└── errors          list of non-fatal error strings
```

---

## File layout

```
src/robotics_daily/
├── cli.py              Entry point — builds context, assembles pipeline, writes output
├── config.py           Pydantic models for feeds.yaml
├── models.py           SourceItem, PostRecommendation data classes
├── dedupe.py           URL canonicalization + SQLite seen-items cache
├── extract.py          Article text extraction (trafilatura + HTTP backoff)
├── rss.py              RSS/Atom feed fetching (feedparser)
├── yahoo_imap.py       Yahoo IMAP email ingestion + link extraction
├── llm.py              LLM API calls (OpenAI or local)
├── render.py           Write posts.md + sources.json output files
└── agents/
    ├── base.py         AgentContext dataclass + BaseAgent abstract class
    ├── pipeline.py     Pipeline orchestrator + StepConfig
    ├── ingestion.py    IngestionAgent
    ├── filter.py       FilterAgent
    ├── scoring_agent.py ScoringAgent + ScoringConfig + math helpers
    ├── content.py      ContentAgent
    └── review.py       ReviewAgent + ReviewConfig
```

---

## Data flow (end to end)

```
config/feeds.yaml
        │
        ▼
   load_config()
        │
        ▼
  AgentContext ──────────────────────────────────────────────────────────────►
        │                                                                      │
        │   IngestionAgent                                                     │
        │   ├── fetch_rss_sources()  ─► feedparser ─► list[SourceItem]        │
        │   └── safe_fetch_newsletter_links()                                  │
        │       └── Yahoo IMAP ─► HTML parse ─► links + anchor text           │
        │       └─► list[SourceItem]                                           │
        │   ctx.raw_items = rss_items + mail_items  (e.g. 100 items)          │
        │                                                                      │
        │   FilterAgent                                                        │
        │   ├── Drop junk URLs (privacy/unsubscribe pages)                     │
        │   ├── Drop trivial excerpts (< 30 chars)                             │
        │   ├── Drop within-run duplicates (title + content hash)              │
        │   ├── enrich_source_excerpt() ─► trafilatura ─► full article text   │
        │   └── cache.seen_recently() ─► drop items seen in last 30 days      │
        │   ctx.validated_items (e.g. 20 items)                                │
        │                                                                      │
        │   ScoringAgent                                                       │
        │   ├── Score each item (relevance·freshness·authority·evidence···)    │
        │   └── pick_top_with_diversity() ─► cap 2 items/domain               │
        │   ctx.ranked_items (e.g. top 10 items by score)                      │
        │                                                                      │
        │   ContentAgent                                                       │
        │   ├── LLM: summarize each item ─► bullets + why_it_matters          │
        │   └── LLM: generate LinkedIn post draft per item                     │
        │   ctx.summarized_items, ctx.posts_markdown                           │
        │                                                                      │
        │   ReviewAgent                                                        │
        │   ├── Classify each item: publish / review / skip                    │
        │   └── cache.mark_seen() ─► flush all items to cache                 │
        │   ctx.recommendations                                                │
        │                                                                      │
        ▼                                                                      │
  write_outputs()                                                              │
  ├── output/YYYY-MM-DD_posts.md      ◄──────────────────────────────────────┘
  └── output/YYYY-MM-DD_sources.json
```

---

## Extending the pipeline

To add a new agent (e.g. a fact-checker), you only touch two things:

1. Create `agents/fact_checker.py` with a class that extends `BaseAgent`
2. Add it to the pipeline in `cli.py`:

```python
pipeline = Pipeline([
    StepConfig(IngestionAgent(), critical=True),
    FilterAgent(),
    ScoringAgent(),
    FactCheckerAgent(),      # ← insert here
    ContentAgent(),
    ReviewAgent(),
])
```

No other file needs to change.

---

## Future: triggering from mobile

The current CLI is already SSH-invokable. To trigger from a mobile phone without SSH, wrap `run_command()` in a small FastAPI endpoint:

```python
# api.py (not yet implemented)
from fastapi import FastAPI
from robotics_daily.cli import run_command

app = FastAPI()

@app.post("/run")
def trigger_run():
    exit_code = run_command("config/feeds.yaml")
    return {"status": "ok" if exit_code == 0 else "error"}
```

Run with: `uvicorn api:app --host 0.0.0.0 --port 8000`

Then call `POST http://your-server:8000/run` from any HTTP client on your phone. No changes to any agent code required.
