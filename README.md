# Hacktoberfest 2026 Tracker

Terminal browser and schedule tracker for Major League Hacking (MLH) Hacktoberfest 2026 events. It scrapes event pages sequentially, caches metadata in SQLite, converts UTC times to your local timezone, and lets you inspect and open event pages directly from your terminal.

## What it does

- **Event scraping**: Fetches MLH event pages from ID 14620 through 15600+ and caches responses in SQLite (`events.db`).
- **Zero-setup clone**: Ships with a pre-scraped snapshot in `hacktoberfest_events.json`. When you clone the repo, the tracker populates the local database on first run without needing a full scrape.
- **Local timezone detection**: Automatically detects your system timezone and converts event start times. You can also specify an offset manually (for example `--tz -4` for EDT or `--tz 5.5` for IST).
- **Realistic live windows**: Many MLH events set their end date to the end of the month as a placeholder. The tracker marks events completed once their meetup day passes so the live view stays accurate.
- **Terminal UI**: Shows upcoming events with countdowns, filters by format (online or in-person), and opens clean event pages in your browser without forcing auto-registration.
- **Prebuilt exports**: Includes a readable Markdown schedule (`hacktoberfest_schedule.md`) and a full JSON export (`hacktoberfest_events.json`).

## Setup

Requires Python 3.12+ and [uv](https://github.com/astral-sh/uv).

Dependencies install automatically into a local `.venv` when running commands through `uv`:

```bash
uv sync
```

## Usage

### Interactive TUI

Launch the tracker with the shortcut:

```bash
./hacktrack
# or:
uv run tui.py
```

To view the schedule in a different timezone, pass the offset in hours:

```bash
./hacktrack --tz -4    # US Eastern (UTC-4)
./hacktrack --tz 5.5   # India Standard Time (UTC+5:30)
```

#### Controls

| Key | Action |
| :--- | :--- |
| `t` | Today and next 24 hours |
| `1` | Upcoming events (default view) |
| `2` | Virtual and online events |
| `3` | Live right now |
| `4` | In-person hack days and meetups |
| `5` | Completed events |
| `6` | All events |
| `1`-`12` | View detail card for a row on screen |
| `<id>` | View detail card by event ID (e.g. `15572`) |
| `o <#>` | Open event page in browser |
| `/ <query>` | Search title, host, or venue |
| `c` | Clear search or filter |
| `n` / `p` | Next or previous page |
| `tz [offset]` | Switch timezone dynamically (e.g. `tz -4`, `tz 5.5`, `tz auto`) |
| `u` | Check for new events |
| `r` | Refresh timers |
| `q` | Quit |

### Non-interactive CLI

Run one-off queries without launching the interactive screen:

```bash
# Next 24 hours in local time
./hacktrack --today

# Upcoming virtual events
./hacktrack --upcoming --online --limit 10

# Search for a topic or city
./hacktrack --search "copilot"
./hacktrack --search "singapore"

# Open an event page in your browser by ID
./hacktrack --open 15572

# Check times under another timezone
./hacktrack --today --tz 0
```

### Checking for updates

MLH adds events and fills in TBA venues throughout the month. You can check for additions from the command line:

```bash
./update
# or:
uv run scraper.py --update
```

(You can also press `u` while inside `./hacktrack`.)

This scans sequentially from the highest known event ID until it hits 25 consecutive 404s, refreshes any events currently marked TBA, and regenerates both `hacktoberfest_events.json` and `hacktoberfest_schedule.md`.

To re-fetch all upcoming events if dates shifted:

```bash
uv run scraper.py --update --refresh-upcoming
```

## Running tests

```bash
PYTHONPATH=. uv run python tests/test_parser.py
```

## Project files

```
hacktoberfest-tracker/
├── hacktrack                    # Executable launcher for the interactive TUI
├── update                       # Executable launcher for incremental updates
├── tui.py                       # Terminal UI and search interface
├── scraper.py                   # Scraper, database manager, and exporter
├── pyproject.toml               # Project configuration and dependencies
├── hacktoberfest_events.json    # Full JSON dataset
├── hacktoberfest_schedule.md    # Formatted Markdown schedule
├── tests/
│   └── test_parser.py           # Unit tests
├── LICENSE                      # MIT License
├── README.md                    # This file
└── AGENTS.md                    # Technical notes and invariants for AI agents
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

