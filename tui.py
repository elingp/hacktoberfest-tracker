#!/usr/bin/env python3
"""
MLH Hacktoberfest 2026 - Enhanced Terminal UI & Event Tracker
Browse upcoming events with humanized countdowns, event detail inspection,
pagination, instant event page opening, and in-app update scanning.
"""

import argparse
from datetime import datetime, timezone, timedelta
import json
import math
import os
import sqlite3
import sys
import webbrowser
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt

from scraper import (
    get_system_tz_offset,
    get_tz_label,
    utc_to_local,
    normalize_event_timing,
    update_events,
)

console = Console()

DB_PATH = "events.db"
DEFAULT_TZ_OFFSET: float = get_system_tz_offset()
PAGE_SIZE = 12


def get_current_local_time(tz_offset: float = DEFAULT_TZ_OFFSET) -> datetime:
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=tz_offset)))


def get_event_page_url(event: Dict[str, Any]) -> str:
    """Return the clean event page URL (without /register)."""
    eid = event.get("event_id")
    raw_url = event.get("url") or f"https://events.mlh.com/events/{eid}"
    if raw_url.endswith("/register"):
        raw_url = raw_url[:-len("/register")]
    return raw_url


def format_countdown(start_utc_str: Optional[str], tz_offset: float = DEFAULT_TZ_OFFSET) -> str:
    """Return a human-friendly countdown to event start."""
    if not start_utc_str:
        return "TBA"
    try:
        start_dt, _ = utc_to_local(start_utc_str, tz_offset)
        if not start_dt:
            return "TBA"
        now = get_current_local_time(tz_offset)
        diff = start_dt - now

        if diff.total_seconds() <= 0:
            past_secs = abs(diff.total_seconds())
            if past_secs < 3600:
                return f"started {int(past_secs // 60)}m ago"
            elif past_secs < 86400:
                return f"started {int(past_secs // 3600)}h ago"
            else:
                return f"started {int(past_secs // 86400)}d ago"

        total_mins = int(diff.total_seconds() // 60)
        days = total_mins // (24 * 60)
        hours = (total_mins % (24 * 60)) // 60
        mins = total_mins % 60

        if days > 0:
            return f"in {days}d {hours}h"
        elif hours > 0:
            return f"in {hours}h {mins}m"
        else:
            return f"in {mins} mins!"
    except Exception:
        return "TBA"


def load_events(db_path: str = DB_PATH, tz_offset: float = DEFAULT_TZ_OFFSET) -> List[Dict[str, Any]]:
    """Load all Hacktoberfest events from SQLite (or bootstrap from JSON if DB missing)."""
    if not os.path.exists(db_path):
        json_fallback = "hacktoberfest_events.json"
        if os.path.exists(json_fallback):
            from scraper import init_db, bootstrap_db_from_json
            conn = init_db(db_path)
            bootstrap_db_from_json(conn, json_fallback)
            conn.close()
        else:
            console.print(f"[bold red]Neither '{db_path}' nor '{json_fallback}' found! Run scraper.py first.[/bold red]")
            sys.exit(1)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT raw_json FROM events
        WHERE is_hacktoberfest = 1
        ORDER BY start_date_utc ASC
    """)
    rows = cursor.fetchall()
    conn.close()

    events = [json.loads(r[0]) for r in rows]
    now = get_current_local_time(tz_offset)

    for e in events:
        normalize_event_timing(e, tz_offset, current_time=now)

    return events


def render_dashboard_header(events: List[Dict[str, Any]], active_filter_label: str, tz_offset: float = DEFAULT_TZ_OFFSET):
    """Display interactive summary header."""
    now = get_current_local_time(tz_offset)
    tz_label = get_tz_label(tz_offset)

    total = len(events)
    valid = [e for e in events if not e.get("is_test")]
    live = sum(1 for e in valid if e.get("status") == "LIVE")
    upcoming = sum(1 for e in valid if e.get("status") == "UPCOMING")
    completed = sum(1 for e in valid if e.get("status") == "COMPLETED")
    virtual = sum(1 for e in valid if e.get("location_type") == "Virtual")
    in_person = sum(1 for e in valid if e.get("location_type") == "In-Person")

    banner_text = (
        f"[bold cyan]🎃 Hacktoberfest 2026 Tracker (hacktrack)[/bold cyan]\n"
        f"[dim]Current Local Time: {now.strftime('%A, %b %d, %Y - %H:%M:%S')} ({tz_label})[/dim]\n\n"
        f"[bold white]Total Events:[/] [cyan]{total}[/]  │  "
        f"🔴 [bold red]Live Now:[/] [red]{live}[/]  │  "
        f"⏳ [bold green]Upcoming:[/] [green]{upcoming}[/]  │  "
        f"✅ [bold blue]Completed:[/] [blue]{completed}[/]  │  "
        f"🌐 [dim]Virtual:[/] {virtual}  │  📍 [dim]In-Person:[/] {in_person}\n"
        f"[bold yellow]Active View:[/] [bold white]{active_filter_label}[/bold white]"
    )
    console.print(Panel(banner_text, border_style="cyan"))


def display_events_table(
    events: List[Dict[str, Any]],
    title: str = "Events",
    page: int = 1,
    page_size: int = PAGE_SIZE,
    tz_offset: float = DEFAULT_TZ_OFFSET,
) -> List[Dict[str, Any]]:
    """Render a paginated Rich table with page-local row numbers."""
    if not events:
        console.print(Panel("[bold yellow]No events match the selected criteria.[/bold yellow]\n[dim]Press [1] to view all upcoming events or [c] to clear filter.[/dim]", border_style="yellow"))
        return []

    total_pages = max(1, math.ceil(len(events) / page_size))
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    current_slice = events[start_idx:end_idx]

    is_wide = console.width >= 105
    tz_label = get_tz_label(tz_offset)

    table = Table(
        title=f"{title} (Showing {start_idx + 1}–{min(end_idx, len(events))} of {len(events)} │ Page {page}/{total_pages})",
        expand=True,
        show_lines=False,
    )
    table.add_column("#", justify="center", style="bold yellow", width=3)
    table.add_column("ID", justify="center", style="cyan", width=5)
    table.add_column("Timing", justify="center", width=13)
    if is_wide:
        table.add_column(f"Start ({tz_label})", style="bold yellow", width=19)
    table.add_column("Title", style="white")
    table.add_column("Format", justify="center", style="cyan", width=11)
    table.add_column("Page", justify="center", width=7)

    for i, e in enumerate(current_slice, start=1):
        eid = str(e.get("event_id"))
        status = e.get("status", "UNKNOWN")
        countdown = format_countdown(e.get("start_date_utc"), tz_offset)

        if status == "LIVE":
            timing_text = Text(f"🔴 Live ({countdown})", style="bold red on yellow")
        elif status == "UPCOMING":
            timing_text = Text(countdown, style="bold green")
        elif status == "COMPLETED":
            timing_text = Text("✅ Done", style="dim")
        else:
            timing_text = Text(status, style="dim")

        start_str = e.get("start_date_local") or e.get("start_date_utc") or "TBA"
        clean_time = start_str.replace(f" {tz_label}", "") if start_str else "TBA"

        loc_type = e.get("location_type", "Virtual")
        if loc_type == "Virtual":
            fmt_str = "🌐 Online"
        else:
            vname = e.get("venue_name") or "In-Person"
            fmt_str = f"📍 {vname[:8]}"

        event_url = get_event_page_url(e)

        row_cells = [
            str(i),
            eid,
            timing_text,
        ]
        if is_wide:
            row_cells.append(clean_time)
        row_cells.extend([
            e.get("title", "Untitled"),
            fmt_str,
            f"[link={event_url}][bold cyan]Open ↗[/bold cyan][/link]",
        ])

        table.add_row(*row_cells)

    console.print(table)
    return current_slice


def open_event_link(event: Dict[str, Any], direct_register: bool = False):
    """Open event page or registration in browser safely."""
    eid = event.get("event_id")
    title = event.get("title", "Untitled")

    if direct_register:
        url = event.get("registration_url") or f"https://events.mlh.com/events/{eid}/register"
        action_name = "Registration Flow"
    else:
        url = get_event_page_url(event)
        action_name = "Event Overview Page"

    console.print(f"\n[bold green]🌐 Opening {action_name} for:[/bold green]\n[bold]{title}[/bold] (ID: {eid})\nURL: [underline blue]{url}[/underline blue]")
    try:
        webbrowser.open(url)
    except Exception as e:
        console.print(f"[yellow]Could not launch browser automatically: {e}. You can open the URL directly.[/yellow]")


def show_event_details(event: Dict[str, Any], tz_offset: float = DEFAULT_TZ_OFFSET):
    """Display rich modal card for a single event."""
    eid = event.get("event_id")
    title = event.get("title", "Untitled")
    series = event.get("series", "Hacktoberfest 2026")
    status = event.get("status", "UNKNOWN")
    countdown = format_countdown(event.get("start_date_utc"), tz_offset)
    tz_label = get_tz_label(tz_offset)

    loc_type = event.get("location_type", "Virtual")
    if loc_type == "Virtual":
        location_info = f"🌐 [bold cyan]Virtual Online Event[/bold cyan]\n[dim]{event.get('location_display', 'Event is hosted online')}[/dim]"
    else:
        location_info = f"📍 [bold yellow]In-Person Venue[/bold yellow]: {event.get('venue_name', 'TBA')}\n[dim]{event.get('address', 'No address provided')}[/dim]"

    host = event.get("hosted_by") or {}
    host_name = host.get("name", "Major League Hacking")

    desc = event.get("description") or "No description provided."
    if len(desc) > 800:
        desc = desc[:800] + "... [dim](truncated)[/dim]"

    event_url = get_event_page_url(event)
    reg_url = event.get("registration_url") or f"https://events.mlh.com/events/{eid}/register"
    ics_url = event.get("calendar_links", {}).get("ics", f"https://events.mlh.com/events/{eid}.ics")
    gcal_url = event.get("calendar_links", {}).get("google_calendar", "")

    resources = event.get("resources", [])
    res_text = ""
    if resources:
        res_lines = ["\n[bold cyan]Attached Links & Resources:[/bold cyan]"]
        for r in resources:
            res_lines.append(f"  • [bold]{r.get('title')}[/bold]: [blue]{r.get('url')}[/blue]")
        res_text = "\n".join(res_lines)

    content = (
        f"[bold white]{title}[/bold white]\n"
        f"[dim]{series}  │  Event ID: {eid}[/dim]\n\n"
        f"Status: [bold green]{status}[/bold green] ([cyan]{countdown}[/cyan])\n"
        f"📅 [bold]Start Time ({tz_label}):[/bold] {event.get('start_date_local', 'TBA')}\n"
        f"📅 [bold]End Time ({tz_label}):[/bold] {event.get('end_date_local', 'TBA')}\n"
        f"📅 [dim]Start Time (UTC):[/dim] {event.get('start_date_utc', 'TBA')}\n"
        f"👤 [bold]Hosted By:[/bold] {host_name}\n\n"
        f"{location_info}\n\n"
        f"[bold]Description:[/bold]\n{desc}\n"
        f"{res_text}\n\n"
        f"🔗 [bold]Event Page URL:[/bold] [underline blue]{event_url}[/underline blue]\n"
        f"📝 [dim]Registration Flow URL:[/dim] [dim]{reg_url}[/dim]\n"
        f"📅 [bold]Calendar ICS:[/bold] [blue]{ics_url}[/blue]"
    )

    console.clear()
    console.print(Panel(content, title=f"Event Details: #{eid}", border_style="cyan"))
    console.print(
        "\n[bold]Actions:[/bold]  "
        "[bold green][o][/bold green] Open Event Page in Browser  │  "
        "[bold magenta][r][/bold magenta] Register Directly  │  "
        "[bold cyan][c][/bold cyan] Open Calendar Link  │  "
        "[bold][b][/bold] Back to List"
    )

    while True:
        try:
            action = Prompt.ask("\nEnter choice", choices=["o", "r", "c", "b"], default="b").strip().lower()
        except (KeyboardInterrupt, EOFError):
            break

        if action == "o":
            open_event_link(event, direct_register=False)
        elif action == "r":
            open_event_link(event, direct_register=True)
        elif action == "c":
            target_cal = gcal_url if gcal_url else ics_url
            console.print(f"[bold green]Opening calendar link:[/bold green] {target_cal}")
            try:
                webbrowser.open(target_cal)
            except Exception:
                pass
        elif action == "b":
            break


def filter_today_events(events: List[Dict[str, Any]], now: datetime, tz_offset: float) -> List[Dict[str, Any]]:
    """Return events starting within the next 24 hours or currently LIVE."""
    next_24h = now + timedelta(hours=24)
    result = []
    for e in events:
        start_dt, _ = utc_to_local(e.get("start_date_utc"), tz_offset)
        if start_dt and (now <= start_dt <= next_24h or e.get("status") == "LIVE"):
            result.append(e)
    return result


def filter_by_search(events: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    """Return events matching query across title, series, description, address, or venue."""
    q = query.lower()
    fields = ("title", "series", "description", "address", "venue_name")
    return [
        e for e in events
        if any(q in (e.get(f) or "").lower() for f in fields)
    ]


FILTER_PRESETS = {
    "t": ("today", "Today / Next 24 Hours"),
    "1": ("upcoming", "Upcoming Events (Yet to be held)"),
    "2": ("virtual_upcoming", "Virtual Upcoming Events"),
    "3": ("live", "Live Right Now"),
    "4": ("in_person", "In-Person Events"),
    "5": ("completed", "Completed Events"),
    "6": ("all", "All Events"),
    "c": ("upcoming", "Upcoming Events (Yet to be held)"),
}


def interactive_loop(events: List[Dict[str, Any]], tz_offset: float = DEFAULT_TZ_OFFSET):
    """Main interactive TUI loop with pagination, safe interrupts, and detail navigation."""
    current_filter = "upcoming"
    filter_label = "Upcoming Events (Yet to be held)"
    search_query = ""
    current_page = 1
    needs_reload = False

    while True:
        try:
            console.clear()
            if needs_reload:
                events = load_events(tz_offset=tz_offset)
                needs_reload = False
            now = get_current_local_time(tz_offset)
            render_dashboard_header(events, filter_label, tz_offset)

            # Filter events
            filtered = [e for e in events if not e.get("is_test")]
            if current_filter == "today":
                filtered = filter_today_events(filtered, now, tz_offset)
            elif current_filter == "upcoming":
                filtered = [e for e in filtered if e.get("status") == "UPCOMING"]
            elif current_filter == "virtual_upcoming":
                filtered = [e for e in filtered if e.get("status") == "UPCOMING" and e.get("location_type") == "Virtual"]
            elif current_filter == "live":
                filtered = [e for e in filtered if e.get("status") == "LIVE"]
            elif current_filter == "in_person":
                filtered = [e for e in filtered if e.get("location_type") == "In-Person"]
            elif current_filter == "completed":
                filtered = [e for e in filtered if e.get("status") == "COMPLETED"]
            elif current_filter == "all":
                pass
            elif current_filter == "search" and search_query:
                filtered = filter_by_search(filtered, search_query)

            total_pages = max(1, math.ceil(len(filtered) / PAGE_SIZE))
            current_page = max(1, min(current_page, total_pages))

            displayed_slice = display_events_table(
                filtered,
                title=f"Filter: {filter_label}",
                page=current_page,
                page_size=PAGE_SIZE,
                tz_offset=tz_offset,
            )

            console.print("\n[bold cyan]Filters & Views:[/bold cyan]")
            console.print(
                "  [bold]t[/]: Today / Next 24h     │  [bold]1[/]: Upcoming (All)       │  [bold]2[/]: Virtual Upcoming\n"
                "  [bold]3[/]: Live Right Now       │  [bold]4[/]: In-Person Events    │  [bold]5[/]: Completed Events\n"
                "  [bold]6[/]: All Events           │  [bold]/[/] <term>: Search        │  [bold]u[/]: Check for New Events"
            )
            console.print("[bold cyan]Selection & Navigation:[/bold cyan]")
            console.print(
                "  [bold]<1-12>[/]: View Event Details on page   │  [bold]<id>[/]: View by 5-digit Event ID\n"
                "  [bold]o <#>[/]: Open Event Page in Browser     │  [bold]c[/]: Clear Filter / Search\n"
                "  [bold]n[/]: Next Page  │  [bold]p[/]: Previous Page  │  [bold]tz <hrs>[/]: Timezone  │  [bold]r[/]: Refresh  │  [bold]q[/]: Quit"
            )

            choice = Prompt.ask("\nEnter command", default="n" if current_page < total_pages else "t").strip()

        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Exiting tracker. Happy Hacktoberfest![/dim]")
            break

        c_lower = choice.lower()

        if c_lower in ("q", "quit", "exit"):
            console.print("[dim]Goodbye![/dim]")
            break
        elif c_lower == "n":
            if current_page < total_pages:
                current_page += 1
        elif c_lower == "p":
            if current_page > 1:
                current_page -= 1
        elif c_lower in FILTER_PRESETS:
            current_filter, filter_label = FILTER_PRESETS[c_lower]
            if c_lower == "c":
                search_query = ""
            current_page = 1
        elif c_lower == "u":
            console.clear()
            console.print("[bold cyan]🔄 Scanning for newly added events on MLH...[/bold cyan]")
            new_count = update_events(tz_offset_hours=tz_offset)
            needs_reload = True
            console.print(f"\n[bold green]Scan complete! Found {new_count} new Hacktoberfest events. Tracker reloaded.[/bold green]")
            try:
                Prompt.ask("\nPress Enter to return to tracker...")
            except (KeyboardInterrupt, EOFError):
                pass
        elif choice.startswith("/") or choice.startswith("search"):
            parts = choice.split(maxsplit=1)
            search_query = parts[1] if len(parts) > 1 else Prompt.ask("Search term").strip()
            current_filter = "search"
            filter_label = f"Search '{search_query}'"
            current_page = 1
        elif choice.startswith("o ") or choice.startswith("open "):
            target_str = choice.split(maxsplit=1)[1].strip()
            try:
                target_val = int(target_str)
                # Check if it's page-local row index 1..PAGE_SIZE
                if 1 <= target_val <= len(displayed_slice):
                    open_event_link(displayed_slice[target_val - 1], direct_register=False)
                else:
                    match = next((e for e in events if e.get("event_id") == target_val), None)
                    if match:
                        open_event_link(match, direct_register=False)
                    else:
                        console.print(f"[red]Event ID {target_val} not found.[/red]")
                try:
                    Prompt.ask("\nPress Enter to continue...")
                except (KeyboardInterrupt, EOFError):
                    pass
            except ValueError:
                console.print("[red]Invalid ID or row number.[/red]")
                try:
                    Prompt.ask("\nPress Enter to continue...")
                except (KeyboardInterrupt, EOFError):
                    pass
        elif choice.isdigit():
            val = int(choice)
            # If 1 <= val <= PAGE_SIZE, it's the row on the CURRENT page!
            if 1 <= val <= len(displayed_slice):
                show_event_details(displayed_slice[val - 1], tz_offset)
            else:
                # Direct event ID search
                match = next((e for e in events if e.get("event_id") == val), None)
                if match:
                    show_event_details(match, tz_offset)
                else:
                    console.print(f"[red]Event ID {val} not found.[/red]")
                    try:
                        Prompt.ask("\nPress Enter to continue...")
                    except (KeyboardInterrupt, EOFError):
                        pass
        elif c_lower.startswith("tz"):
            parts = choice.split(maxsplit=1)
            raw_input = parts[1].strip() if len(parts) > 1 else ""
            if not raw_input:
                try:
                    raw_input = Prompt.ask("Enter timezone offset in hours (e.g. -4, 5.5, or 'auto')").strip()
                except (KeyboardInterrupt, EOFError):
                    raw_input = ""
            if raw_input:
                val = raw_input.lower()
                if val in ("auto", "host", "reset"):
                    tz_offset = get_system_tz_offset()
                    needs_reload = True
                    console.print(f"[bold green]Timezone reset to auto-detected host ({get_tz_label(tz_offset)})[/bold green]")
                else:
                    try:
                        parsed_tz = float(val)
                        if -12.0 <= parsed_tz <= 14.0:
                            tz_offset = parsed_tz
                            needs_reload = True
                            console.print(f"[bold green]Timezone switched to {get_tz_label(tz_offset)}[/bold green]")
                        else:
                            console.print(f"[bold red]Timezone offset must be between -12 and +14 hours (got {parsed_tz}).[/bold red]")
                    except ValueError:
                        console.print(f"[bold red]Invalid timezone offset: '{raw_input}'. Use hours (e.g. 'tz -4', 'tz 5.5', 'tz auto').[/bold red]")
                try:
                    Prompt.ask("\nPress Enter to continue...")
                except (KeyboardInterrupt, EOFError):
                    pass
        elif c_lower == "r":
            needs_reload = True
            continue


def main():
    parser = argparse.ArgumentParser(description="hacktrack: MLH Hacktoberfest 2026 Event Tracker & TUI")
    parser.add_argument("--upcoming", action="store_true", help="Print upcoming events and exit")
    parser.add_argument("--today", action="store_true", help="Print today's events (next 24h) and exit")
    parser.add_argument("--live", action="store_true", help="Print live events and exit")
    parser.add_argument("--online", action="store_true", help="Filter to virtual/online only")
    parser.add_argument("--search", type=str, help="Search events by keyword")
    parser.add_argument("--open", type=int, help="Open event page for ID in browser")
    parser.add_argument("--limit", type=int, default=PAGE_SIZE, help=f"Limit number of rows printed (default: {PAGE_SIZE})")
    parser.add_argument("--tz", type=float, default=None, help="Local timezone offset in hours (default: auto-detected host timezone)")
    parser.add_argument("--interactive", "-i", action="store_true", help="Launch interactive TUI (default if no flags)")
    args = parser.parse_args()

    tz_offset = args.tz if args.tz is not None else get_system_tz_offset()
    events = load_events(tz_offset=tz_offset)

    if args.open:
        match = next((e for e in events if e.get("event_id") == args.open), None)
        if match:
            open_event_link(match, direct_register=False)
        else:
            console.print(f"[red]Event ID {args.open} not found.[/red]")
        return

    if args.upcoming or args.today or args.live or args.search or args.online:
        now = get_current_local_time(tz_offset)
        filtered = [e for e in events if not e.get("is_test")]
        label = "Events"

        if args.today:
            filtered = filter_today_events(filtered, now, tz_offset)
            label = "Today / Next 24 Hours " + label
        elif args.upcoming:
            filtered = [e for e in filtered if e.get("status") == "UPCOMING"]
            label = "Upcoming " + label
        elif args.live:
            filtered = [e for e in filtered if e.get("status") == "LIVE"]
            label = "Live " + label

        if args.online:
            filtered = [e for e in filtered if e.get("location_type") == "Virtual"]
            label += " (Online)"

        if args.search:
            filtered = filter_by_search(filtered, args.search)
            label += f" matching '{args.search}'"

        render_dashboard_header(events, label, tz_offset=tz_offset)
        display_events_table(filtered, title=label, page=1, page_size=args.limit or PAGE_SIZE, tz_offset=tz_offset)
        return

    interactive_loop(events, tz_offset=tz_offset)


if __name__ == "__main__":
    main()
