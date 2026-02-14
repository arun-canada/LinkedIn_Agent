# robotics_daily

Windows-friendly CLI to generate daily social media post drafts about autonomy + robotics (with focus on **Simulation, Automation, Validation**), using:

- RSS feeds
- Yahoo Mail newsletters via IMAP
- Lightweight page fetch + text extraction (no headless browser)

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

Set env vars:

```bash
set OPENAI_API_KEY=your_key_here
set YAHOO_EMAIL=you@yahoo.com
set YAHOO_APP_PASSWORD=your_yahoo_app_password
```

Run:

```bash
python -m robotics_daily.cli run
```

Outputs:

- `output/YYYY-MM-DD_posts.md`
- `output/YYYY-MM-DD_sources.json`
- local cache: `cache.db`
- logs: `logs/app.log`

## CLI

Primary command:

```bash
robotics_daily run
```

In this repo, use:

```bash
python -m robotics_daily.cli run --config config/feeds.yaml
```

## Config

Edit `config/feeds.yaml`:

- RSS feed list
- Yahoo IMAP settings
- newsletter sender/domain allowlist
- newsletter subject keywords
- scoring topics
- selection limits (`max_items`, `max_posts`)

## How Yahoo app password works

1. Log into Yahoo account security settings.
2. Enable 2-step verification (if not already enabled).
3. Generate an **App Password** for Mail.
4. Use that app password as `YAHOO_APP_PASSWORD` (not your account password).

## Reliability behavior

- HTTP fetches use timeout + retry/backoff for 429/5xx.
- If Yahoo IMAP fails, run continues with RSS-only.
- If RSS fails, run continues with Yahoo-only.
- Dedupe uses URL canonicalization + content hash and skips seen items within 30 days.

## OpenAI behavior

`OPENAI_API_KEY` is required for LLM summarization/post generation.

The app asks the model to:

- summarize top sources into bullets + “why it matters”
- produce 1–3 LinkedIn-style drafts
- include source links
- avoid uncertain precise numeric claims

## Windows Task Scheduler (daily run)

1. Open **Task Scheduler** → **Create Basic Task**.
2. Trigger: Daily.
3. Action: Start a program.
4. Program/script: path to `python.exe` (or packaged `robotics_daily.exe`).
5. Add arguments: `-m robotics_daily.cli run` (for Python) or `run` if using the packaged exe
6. Start in: project folder path.

## Build `.exe` with PyInstaller

From project root:

```bash
pyinstaller --onefile --name robotics_daily src/robotics_daily/cli.py
```

The executable will be in `dist/robotics_daily.exe`.

## Tests

Run:

```bash
pytest -q
```

Current tests cover URL canonicalization and SQLite dedupe logic.
