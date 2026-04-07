# robotics_daily

CLI agent that monitors robotics and autonomy news, scores it for relevance, and generates LinkedIn post drafts — ready to review and publish.

Runs on Linux/macOS/Windows. Invokable via terminal, SSH, or (future) HTTP trigger from a mobile phone.

---

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

Copy `.env.example` to `.env` and fill in your credentials:

```bash
# LLM provider — choose one
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini

# Or use a local model (e.g. Ollama)
# LLM_PROVIDER=local
# LOCAL_MODEL=llama3.2
# LOCAL_BASE_URL=http://localhost:11434/v1

# Yahoo Mail (for newsletter ingestion)
YAHOO_EMAIL=you@yahoo.com
YAHOO_APP_PASSWORD=your_yahoo_app_password
```

Run:

```bash
python -m robotics_daily.cli run
```

---

## Output

Each run produces two files in `output/`:

| File | Contents |
|------|----------|
| `YYYY-MM-DD_posts.md` | LinkedIn post drafts + quality review table |
| `YYYY-MM-DD_sources.json` | Full metadata for all scored sources |

Also written: `cache.db` (SQLite dedup cache), `logs/app.log`.

---

## CLI flags

```bash
python -m robotics_daily.cli run --config config/feeds.yaml   # default
python -m robotics_daily.cli run --debug                      # per-item verbose logging

# Telegram notifications
python -m robotics_daily.cli run --notify                     # send top 2 picks to phone
python -m robotics_daily.cli run --notify --top 5             # send top 5 picks
python -m robotics_daily.cli run --notify --pdf               # send full posts as PDF
```

`--debug` shows what each agent ingested, filtered, scored, and why — useful for diagnosing missing articles.

`--notify` sends results to your phone via Telegram after the run. Requires `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env` (see below). Local file output is always written regardless of this flag.

---

## Telegram setup (for `--notify`)

1. Open Telegram and search for **@BotFather**.
2. Send `/newbot` and follow the prompts. Copy the **token** it gives you.
3. Set in `.env`:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC-your-token-here
   ```
4. Start a conversation with your new bot (search its name in Telegram).
5. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` — copy the `"id"` value from the `"chat"` object.
6. Set in `.env`:
   ```
   TELEGRAM_CHAT_ID=987654321
   ```

Run with `--notify` and you'll receive a formatted message on your phone after each pipeline run.

---

## Configuration (`config/feeds.yaml`)

```yaml
rss_feeds:
  - name: The Robot Report
    url: https://www.therobotreport.com/feed/

newsletter:
  enabled: true
  days_back: 7             # look back N days for emails (match your run frequency)
  from_allowlist:          # only process emails from these senders
    - weeklyrobotics.com
    - therobotreport.com
  subject_keywords: []     # leave empty to accept all allowlisted senders

selection:
  max_items: 15            # items to score and summarize
  max_posts: 15            # post drafts to generate

output:
  dir: output
```

**Important:** Set `days_back` to match how often you run the pipeline. If you run weekly, set `days_back: 7`. If you miss a run, newsletter articles will fall outside the window and be skipped.

---

## Yahoo app password setup

1. Log into [Yahoo Account Security](https://login.yahoo.com/account/security).
2. Enable **2-step verification**.
3. Generate an **App Password** for Mail.
4. Use that password as `YAHOO_APP_PASSWORD` (not your Yahoo account password).

---

## Reliability

- HTTP fetches use timeout + exponential backoff for 429/5xx errors.
- If Yahoo IMAP fails, the run continues with RSS sources only.
- Deduplication uses URL canonicalization + content hash; items seen within 30 days are skipped.
- To reprocess all items: `rm cache.db`

---

## Scheduling

**Linux/macOS (cron) — run every Monday at 8am:**

```bash
# Without notifications
0 8 * * 1 cd /path/to/LinkedIn_Agent && .venv/bin/python -m robotics_daily.cli run >> logs/cron.log 2>&1

# With Telegram notification (top 2 picks sent to phone)
0 8 * * 1 cd /path/to/LinkedIn_Agent && .venv/bin/python -m robotics_daily.cli run --notify >> logs/cron.log 2>&1
```

**Windows Task Scheduler:**

1. Task Scheduler → Create Basic Task → Trigger: Weekly.
2. Action: Start a program.
3. Program: `C:\path\to\.venv\Scripts\python.exe`
4. Arguments: `-m robotics_daily.cli run`
5. Start in: `C:\path\to\LinkedIn_Agent`

---

## Tests

```bash
pytest -q
```

Tests cover URL canonicalization and SQLite dedup logic (`tests/test_dedupe.py`).

---

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for a detailed explanation of how the pipeline works.
