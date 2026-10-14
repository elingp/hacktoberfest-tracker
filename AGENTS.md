# AGENTS.md — Technical Architecture & Agent Guidelines

This document provides context, design decisions, invariants, and operational guidelines for AI coding agents working on the `hacktoberfest-tracker` repository.

---

## 1. Project Overview & Scope

The repository scrapes, parses, normalizes, and tracks Major League Hacking (MLH) Hacktoberfest 2026 events.
- **Target Site**: `events.mlh.com`
- **Indexing Model**: Sequential numeric IDs (e.g., `https://events.mlh.com/events/15572`).
- **Discovered Range**: `14620` (first Hacktoberfest 2026 event) through `15600+`.
- **Timezone Architecture**: Auto-detected host system local timezone by default (e.g., UTC+8, EDT, IST), with integer and float `--tz <hours>` CLI override support across TUI, scraper, and exporters.
- **Primary Interfaces**:
  - `tui.py` / `./hacktrack` (Interactive Terminal UI built with Rich)
  - `scraper.py` / `./update` (Multi-threaded connection-pooled scraper & exporter)
  - Pre-generated datasets (`hacktoberfest_events.json`, `hacktoberfest_schedule.md`)

---

## 2. Environment & Dependency Rules

> [!CAUTION]
> **NEVER install Python packages into the global environment.**
> Running `python3 -m pip install` globally is strictly forbidden.

- **Package Manager**: Always use [`uv`](https://github.com/astral-sh/uv).
- **Virtual Environment**: Located at `.venv/` at repository root.
- **Running Commands**:
  - Use `uv run <command>` (e.g., `uv run python ...`, `uv run tui.py`).
  - Or use the root shortcut wrappers: `./hacktrack` and `./update`.
- **Dependencies** (defined in `pyproject.toml`):
  - `beautifulsoup4`
  - `requests`
  - `rich`

---

## 3. Architecture & Data Flow

```
[events.mlh.com/events/<id>]
           │
           ▼
     [scraper.py]
  (ThreadPoolExecutor)
           │
     ┌─────┴────────────────────────┐
     ▼                              ▼
[events.db] (SQLite)          [Data Normalizer]
 - checked_ids (404/200 cache)  - Dynamic UTC -> Local conversion (auto-detected or --tz)
 - events (full metadata)       - Strict Live window resolution
                                - Hacktoberfest classifier
                                - TBA / Rolling update refresher
                                    │
                       ┌────────────┴─────────────┐
                       ▼                          ▼
           [hacktoberfest_events.json]   [hacktoberfest_schedule.md]
                       │
                       ▼
                    [tui.py]
               (Interactive Terminal UI)
         *Auto-bootstraps events.db if missing*
```

### Database Layer (`events.db`)
SQLite database used for persistence and resuming:
- `checked_ids`: `(event_id, http_status, checked_at)` — Records terminal HTTP responses (`200` and `404`). Ensures non-existent IDs and already parsed events are never redundantly requested across runs. Transient network timeouts and server errors are omitted so they can be retried on subsequent runs.
- `events`: Stores structured event fields, timestamps, series, location, and the `raw_json` payload.
- **Git State**: `events.db` is strictly gitignored so binary SQLite blobs are not committed to git.

---

## 4. Critical Design Invariants (DO NOT BREAK)

### Invariant 1: Event URLs Must Point to the Overview Page, NOT `/register`
- **Context**: The user explicitly requested to view the event details first before deciding whether to register. Registering automatically or linking directly to `/register` looks suspicious and prevents picking/choosing.
- **Rule**:
  - Primary URL (`url`) must always be the clean event page: `https://events.mlh.com/events/<id>` (or clean canonical slug without `/register`).
  - Never override the main table link or direct browser action with `/register`.
  - In `tui.py`, `open_event_link` defaults to `direct_register=False`. Direct registration is only exposed as a secondary action inside the detailed card inspection modal.

### Invariant 2: Strict Live Session Window (Preventing Multi-Day Pollution)
- **Context**: On MLH, organizers frequently set end dates to the end of the month (e.g. October 1 to October 31) as placeholders. If status is naively calculated as `start <= now <= end`, a 1-day Hack Day held on October 1st remains marked as **"🔴 LIVE NOW"** for 30 consecutive days, polluting the Live view with dead/past events.
- **Rule in `get_event_status()`**:
  - An event is ONLY `LIVE` if:
    1. Current time is between `start_date` and `effective_end_date`.
    2. The scheduled session duration is realistic for a live gathering ($\le 36$ hours).
    3. If duration $> 36$ hours, it is only considered actively live on day 1 (within 24 hours of start).
  - Any event whose start date was days ago automatically transitions to `COMPLETED`.

### Invariant 3: Absence of Public "Canceled" Status on MLH
- **Context**: MLH does not publish `eventStatus: EventCancelled` or cancellation flags on public HTML pages. When an event is abandoned or completed, its page remains `HTTP 200`.
- **Rule**: Do not attempt to parse a non-existent "canceled" badge. Rely on the strict start/end duration resolution rule above to transition past events to `COMPLETED`.

### Invariant 4: Responsive Terminal UI Formatting
- **Context**: Terminal widths vary (default non-interactive shell is 80 columns; user windows range from 80 to 160+).
- **Rule**:
  - Fixed columns (`#`, `ID`, `Timing`, `Format`, `Page`) must specify compact explicit widths so they never truncate with ellipses (`…`) on 80-column terminals.
  - The `Start (<tz_label>)` column is only displayed when `console.width >= 105`.
  - Links in tables use Rich terminal hyperlinks (`[link=URL]Open ↗[/link]`) to prevent long URLs from consuming 60+ horizontal characters.

### Invariant 5: Zero-Setup SQLite Bootstrapping on Clone
- **Context**: `events.db` is excluded from git. A newly cloned workspace only has `hacktoberfest_events.json`.
- **Rule**: Both `tui.py` and `scraper.py` must check if `events.db` exists. If missing, they auto-populate `events` and `checked_ids` directly from `hacktoberfest_events.json` using the shared `bootstrap_db_from_json(conn, json_path)` helper before querying. This allows anyone cloning the repository to run `./hacktrack` immediately without scraping.

---

## 5. Standard Development & Verification Commands

### Run Unit Tests
```bash
PYTHONPATH=. uv run python tests/test_parser.py
```
*Tests cover: HTML microdata parsing, in-person physical venue and address extraction, UTC to local conversion, live/upcoming/completed status resolution, multi-day past event handling, JSON database bootstrapping, TUI filtering helpers, and Hacktoberfest series classification.*

### Run Scraper Updates (Incremental + TBA Refresh)
```bash
./update
# Or:
uv run scraper.py --update
```
*Refreshes existing TBA/TBD events and probes upwards from the highest existing ID in `events.db` until 25 consecutive 404s are reached, then regenerates JSON and Markdown outputs.*

### Re-fetch All Upcoming Events
```bash
uv run scraper.py --update --refresh-upcoming
```

### Force Re-export Without Scraping
```bash
uv run scraper.py --export-only
```

### Launch Interactive TUI
```bash
./hacktrack
# Or with explicit timezone:
./hacktrack --tz -4    # US Eastern
./hacktrack --tz 5.5   # India Standard Time
```

### Non-Interactive CLI Queries
```bash
./hacktrack --upcoming --online --limit 10
./hacktrack --today
./hacktrack --search "copilot"
./hacktrack --open 15572
```
