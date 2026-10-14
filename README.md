# Hacktoberfest 2026 Tracker

A terminal browser and schedule tracker for Major League Hacking (MLH) Hacktoberfest 2026 events. It scrapes event pages sequentially, caches metadata in SQLite, converts UTC times to your local timezone, and lets you inspect and open event pages directly from your terminal.

## Features

- Scrapes MLH event pages from ID 14620 through 15600+ and caches responses in SQLite (`events.db`).
- Includes a pre-scraped snapshot in `hacktoberfest_events.json`. When you clone the repository, the tracker populates the local database on first run, so you do not have to run a full scrape before using it.
- Automatically detects your system timezone and converts event start times. You can also specify an offset manually (for example `--tz -4` for EDT or `--tz 5.5` for IST).
- Handles multi-day placeholder dates. Organizers often set the end date to the end of the month even for one-day meetups. The tracker marks events completed once their meetup day passes to keep the live view accurate.
- Terminal interface with countdown timers, filters for online or in-person events, and direct links to event overview pages.
- Generates a Markdown schedule (`hacktoberfest_schedule.md`) and a full JSON export (`hacktoberfest_events.json`).

## Setup

Requires Python 3.12+ and [uv](https://github.com/astral-sh/uv).

Install dependencies into a local virtual environment:

```bash
uv sync
```

## Usage

### Interactive terminal UI

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

Run queries from the command line without launching the interactive screen:

```bash
# Next 24 hours in local time
./hacktrack --today

# Virtual events in the next 24 hours
./hacktrack --today --online

# Upcoming virtual events
./hacktrack --upcoming --online --limit 10

# Search by topic or city
./hacktrack --search "copilot"
./hacktrack --search "singapore"

# Open an event page in your browser by ID
./hacktrack --open 15572

# Check times under another timezone
./hacktrack --today --tz 0
```

### Checking for updates

MLH adds events and updates venue details throughout the month. You can check for additions from the command line:

```bash
./update
# or:
uv run scraper.py --update
```

You can also press `u` while running `./hacktrack`.

This scans sequentially from the highest known event ID until it encounters 25 consecutive 404 responses, refreshes any events currently marked TBA, and updates both `hacktoberfest_events.json` and `hacktoberfest_schedule.md`.

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
├── hacktrack                    # Launcher for the interactive terminal UI
├── update                       # Launcher for incremental updates
├── tui.py                       # Terminal UI and search interface
├── scraper.py                   # Scraper, database manager, and exporter
├── pyproject.toml               # Project configuration and dependencies
├── hacktoberfest_events.json    # Full JSON dataset
├── hacktoberfest_schedule.md    # Formatted Markdown schedule
├── tests/
│   └── test_parser.py           # Unit tests
├── LICENSE                      # MIT License
├── README.md                    # Project documentation
└── AGENTS.md                    # Technical notes and architecture guidelines
```

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
