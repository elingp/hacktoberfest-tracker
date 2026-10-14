#!/usr/bin/env python3
"""
MLH Hacktoberfest 2026 Event Tracker & Scraper
Fetches event details using sequential event IDs, stores in SQLite/JSON,
normalizes timestamps to local timezone, and categorizes status.
"""

import argparse
import concurrent.futures
from datetime import datetime, timezone, timedelta
import json
import logging
import os
import re
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("mlh_scraper")

BASE_URL = "https://events.mlh.com"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def get_system_tz_offset() -> float:
    """Detect host machine local timezone offset in hours (e.g. 8.0 for UTC+8, 5.5 for UTC+5:30)."""
    now_local = datetime.now().astimezone()
    offset = now_local.utcoffset()
    if offset is not None:
        return offset.total_seconds() / 3600.0
    return 0.0


def get_tz_label(tz_offset_hours: float) -> str:
    """Return formatted UTC offset label like 'UTC+08:00' or 'UTC+05:30'."""
    sign = "+" if tz_offset_hours >= 0 else "-"
    total_mins = int(round(abs(tz_offset_hours) * 60))
    hours = total_mins // 60
    mins = total_mins % 60
    return f"UTC{sign}{hours:02d}:{mins:02d}"


def utc_to_local(utc_str: Optional[str], tz_offset_hours: Optional[float] = None) -> Tuple[Optional[datetime], Optional[str]]:
    """Convert UTC timestamp string (Schema.org or ISO 8601) to local datetime and formatted string."""
    if not utc_str:
        return None, None
    if tz_offset_hours is None:
        tz_offset_hours = get_system_tz_offset()
    try:
        clean_str = utc_str.replace(" UTC", "").strip()
        if "T" in clean_str:
            clean_str = clean_str.replace("Z", "+00:00")
            dt_utc = datetime.fromisoformat(clean_str).astimezone(timezone.utc)
        else:
            dt_utc = datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        target_tz = timezone(timedelta(hours=tz_offset_hours))
        dt_local = dt_utc.astimezone(target_tz)
        offset_str = get_tz_label(tz_offset_hours)
        return dt_local, dt_local.strftime(f"%Y-%m-%d %H:%M:%S {offset_str}")
    except Exception as e:
        logger.debug(f"Failed to parse datetime '{utc_str}': {e}")
        return None, None


def get_event_status(
    start_utc_str: Optional[str],
    end_utc_str: Optional[str],
    current_time: Optional[datetime] = None,
    tz_offset_hours: Optional[float] = None,
    max_live_session_hours: int = 36,
) -> str:
    """
    Determine event status: UPCOMING, LIVE, or COMPLETED.
    Prevents multi-day / month-long events from showing as 'LIVE' long after
    their initial gathering day has passed.
    """
    if tz_offset_hours is None:
        if current_time and current_time.utcoffset() is not None:
            tz_offset_hours = current_time.utcoffset().total_seconds() / 3600.0
        else:
            tz_offset_hours = get_system_tz_offset()
    target_tz = timezone(timedelta(hours=tz_offset_hours))
    now = current_time or datetime.now(timezone.utc).astimezone(target_tz)

    start_dt, _ = utc_to_local(start_utc_str, tz_offset_hours)
    end_dt, _ = utc_to_local(end_utc_str, tz_offset_hours)

    if not start_dt:
        return "UNKNOWN"

    if now < start_dt:
        return "UPCOMING"

    effective_end_dt = end_dt or (start_dt + timedelta(hours=3))

    if now > effective_end_dt:
        return "COMPLETED"

    duration = (effective_end_dt - start_dt).total_seconds() / 3600
    elapsed_since_start = (now - start_dt).total_seconds() / 3600

    # If the event is a standard session or weekend hackathon (<= 36h)
    if duration <= max_live_session_hours:
        return "LIVE"
    else:
        # For multi-day or month-long events, only treat as active on day 1 (within 24h of start)
        if elapsed_since_start <= 24:
            return "LIVE"
        else:
            return "COMPLETED"


def classify_event(title: Optional[str], series: Optional[str]) -> Tuple[bool, bool]:
    """
    Check if an event belongs to Hacktoberfest 2026.
    Returns (is_hacktoberfest, is_test).
    """
    t = (title or "").lower()
    s = (series or "").lower()

    # Test event check
    is_test = False
    if "test" in t or "test" in s:
        is_test = True

    # Hacktoberfest checks:
    # 1. Explicit Hacktoberfest series
    if "hacktoberfest" in s:
        return True, is_test

    # 2. Hacktoberfest in title
    if "hacktoberfest" in t or "hack 4 humanity" in t:
        return True, is_test

    # 3. GHW Hacktoberfest livestreams
    if "ghw" in s and "hacktoberfest" in t:
        return True, is_test
    if "[ghw hacktoberfest]" in t or "ghw: hacktoberfest" in t:
        return True, is_test

    # 4. Hacking with GitHub Copilot / Google AI Studio during October
    if "hacking with github copilot" in s or "intro to google ai studio" in s:
        return True, is_test

    return False, is_test


def fetch_event_html(event_id: int, session: Optional[requests.Session] = None) -> Tuple[int, Optional[str]]:
    """Fetch HTML for a given event ID. Returns (http_status, html_content)."""
    url = f"{BASE_URL}/events/{event_id}"
    s = session or requests.Session()
    try:
        response = s.get(url, headers=DEFAULT_HEADERS, timeout=10)
        if response.status_code == 200:
            return 200, response.text
        return response.status_code, None
    except requests.RequestException as e:
        logger.debug(f"Request failed for event {event_id}: {e}")
        return 0, None


def parse_event(html: str, event_id: int, tz_offset_hours: Optional[float] = None) -> Dict[str, Any]:
    """Parse HTML and extract all structured event metadata."""
    if tz_offset_hours is None:
        tz_offset_hours = get_system_tz_offset()
    soup = BeautifulSoup(html, "html.parser")
    data: Dict[str, Any] = {"event_id": event_id}

    # Canonical / OG URL
    og_url = soup.find("meta", property="og:url")
    data["url"] = og_url["content"] if og_url and og_url.get("content") else f"{BASE_URL}/events/{event_id}"

    # Title / Event Name
    title_el = soup.find("h1", itemprop="name")
    if title_el:
        data["title"] = title_el.get_text(strip=True)
    else:
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            data["title"] = og_title["content"].replace(" | Major League Hacking", "").strip()
        else:
            data["title"] = None

    # Series / Subtitle
    series_el = soup.find("h4", class_=re.compile(r"text-mid-gray"))
    data["series"] = series_el.get_text(strip=True) if series_el else None

    # Classification
    is_hf, is_test = classify_event(data["title"], data["series"])
    data["is_hacktoberfest"] = is_hf
    data["is_test"] = is_test

    # Timing: Schema.org microdata (UTC timestamps)
    start_meta = soup.find("meta", itemprop="startDate")
    end_meta = soup.find("meta", itemprop="endDate")
    data["start_date_utc"] = start_meta["content"] if start_meta and start_meta.get("content") else None
    data["end_date_utc"] = end_meta["content"] if end_meta and end_meta.get("content") else None

    # Timing: Converted to local timezone (host system default or explicit --tz)
    _, local_start_str = utc_to_local(data["start_date_utc"], tz_offset_hours)
    _, local_end_str = utc_to_local(data["end_date_utc"], tz_offset_hours)
    data["start_date_local"] = local_start_str
    data["end_date_local"] = local_end_str

    # Status: UPCOMING / LIVE / COMPLETED
    data["status"] = get_event_status(data["start_date_utc"], data["end_date_utc"], tz_offset_hours=tz_offset_hours)

    # Timing: Human-readable display from original page
    clock_icon = soup.find("i", class_=re.compile(r"fa-clock"))
    data["date_display"] = None
    data["time_display"] = None
    if clock_icon:
        parent_div = clock_icon.find_parent("div")
        if parent_div:
            info_div = parent_div.find_next_sibling("div")
            if info_div:
                date_el = info_div.find("div", class_=re.compile(r"text-semibold"))
                if date_el:
                    data["date_display"] = date_el.get_text(strip=True)
                time_el = info_div.find("div", class_=re.compile(r"font-size-6"))
                if time_el:
                    spans = [s.get_text(strip=True) for s in time_el.find_all("span")]
                    data["time_display"] = " ".join(spans)

    # Location Information (Virtual or Physical Venue)
    location_el = soup.find(attrs={"itemprop": "location"})
    data["location_type"] = "Virtual"
    data["location_display"] = None
    data["venue_name"] = None
    data["address"] = None

    if location_el:
        nested_place = location_el.find(attrs={"itemtype": re.compile(r"Place")})
        if nested_place:
            data["location_type"] = "In-Person"
            vname = nested_place.find(attrs={"itemprop": "name"})
            data["venue_name"] = vname.get_text(strip=True) if vname else None
            addr_pre = nested_place.find("pre")
            data["address"] = addr_pre.get_text("\n", strip=True) if addr_pre else None
        else:
            itemtype = location_el.get("itemtype", "")
            if "Place" in itemtype:
                data["location_type"] = "In-Person"
                vname = location_el.find(attrs={"itemprop": "name"})
                data["venue_name"] = vname.get_text(strip=True) if vname else None
                addr_pre = location_el.find("pre")
                data["address"] = addr_pre.get_text("\n", strip=True) if addr_pre else None
            else:
                data["location_type"] = "Virtual"
                loc_txt = location_el.find("div", class_=re.compile(r"text-semibold"))
                data["location_display"] = loc_txt.get_text(strip=True) if loc_txt else "Event is hosted online"

    # Description
    desc_el = soup.find("div", itemprop="description")
    if desc_el:
        text = desc_el.get_text("\n", strip=True)
        if text.startswith("Event Description"):
            text = text[len("Event Description"):].strip()
        data["description"] = text
    else:
        meta_desc = soup.find("meta", attrs={"name": "description"})
        data["description"] = meta_desc["content"] if meta_desc and meta_desc.get("content") else None

    # Cover / Banner Image
    og_img = soup.find("meta", property="og:image")
    data["banner_image"] = og_img["content"] if og_img and og_img.get("content") else None

    # Organizer / Host
    data["hosted_by"] = None
    host_header = soup.find(lambda el: el.name == "h4" and "Hosted by" in el.get_text())
    if host_header:
        host_wrapper = host_header.find_parent("div")
        if host_wrapper:
            host_name_el = host_wrapper.find("div", class_=re.compile(r"font-weight-semibold"))
            host_avatar_el = host_wrapper.find("img", class_=re.compile(r"avatar"))
            data["hosted_by"] = {
                "name": host_name_el.get_text(strip=True) if host_name_el else None,
                "avatar_url": host_avatar_el["src"] if host_avatar_el and host_avatar_el.get("src") else None,
            }

    # Registration Link
    reg_link = soup.find("a", href=re.compile(r"/register"))
    if reg_link and reg_link.get("href"):
        data["registration_url"] = urljoin(BASE_URL, reg_link["href"])
    else:
        data["registration_url"] = None

    # Calendar Integration Links
    calendar_links = {}
    gcal = soup.find("a", href=re.compile(r"google\.com/calendar"))
    if gcal and gcal.get("href"):
        calendar_links["google_calendar"] = gcal["href"]
    ics = soup.find("a", href=re.compile(r"\.ics"))
    if ics and ics.get("href"):
        calendar_links["ics"] = urljoin(BASE_URL, ics["href"])
    data["calendar_links"] = calendar_links

    # Links & Resources
    resources = []
    res_header = soup.find(lambda el: el.name == "h4" and "Links & Resources" in el.get_text())
    if res_header:
        res_container = res_header.find_parent("div")
        if res_container:
            for card in res_container.find_all("div", class_=re.compile(r"card")):
                t = card.find("h6")
                d = card.find("p")
                a = card.find("a", href=True)
                if t or a:
                    resources.append({
                        "title": t.get_text(strip=True) if t else None,
                        "description": d.get_text(strip=True) if d else None,
                        "url": a["href"] if a else None,
                    })
    data["resources"] = resources

    return data


# --- Database Layer ---

def init_db(db_path: str = "events.db") -> sqlite3.Connection:
    """Initialize SQLite database schema."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS checked_ids (
                event_id INTEGER PRIMARY KEY,
                http_status INTEGER NOT NULL,
                checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY,
                title TEXT,
                series TEXT,
                is_hacktoberfest BOOLEAN,
                is_test BOOLEAN,
                start_date_utc TEXT,
                end_date_utc TEXT,
                start_date_local TEXT,
                end_date_local TEXT,
                status TEXT,
                location_type TEXT,
                location_display TEXT,
                venue_name TEXT,
                address TEXT,
                description TEXT,
                banner_image TEXT,
                registration_url TEXT,
                url TEXT,
                raw_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    return conn


def get_checked_ids(conn: sqlite3.Connection) -> Set[int]:
    """Retrieve all IDs already fetched."""
    cursor = conn.cursor()
    cursor.execute("SELECT event_id FROM checked_ids")
    return {row[0] for row in cursor.fetchall()}


def save_event_to_db(conn: sqlite3.Connection, event: Dict[str, Any]):
    """Insert or update event in the database."""
    with conn:
        conn.execute("""
            INSERT OR REPLACE INTO events (
                event_id, title, series, is_hacktoberfest, is_test,
                start_date_utc, end_date_utc, start_date_local, end_date_local,
                status, location_type, location_display, venue_name, address,
                description, banner_image, registration_url, url, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event["event_id"],
            event.get("title"),
            event.get("series"),
            1 if event.get("is_hacktoberfest") else 0,
            1 if event.get("is_test") else 0,
            event.get("start_date_utc"),
            event.get("end_date_utc"),
            event.get("start_date_local"),
            event.get("end_date_local"),
            event.get("status"),
            event.get("location_type"),
            event.get("location_display"),
            event.get("venue_name"),
            event.get("address"),
            event.get("description"),
            event.get("banner_image"),
            event.get("registration_url"),
            event.get("url"),
            json.dumps(event, ensure_ascii=False)
        ))


def record_checked_id(conn: sqlite3.Connection, event_id: int, status_code: int):
    """Record checked ID status."""
    with conn:
        conn.execute("""
            INSERT OR REPLACE INTO checked_ids (event_id, http_status)
            VALUES (?, ?)
        """, (event_id, status_code))


def export_dataset(
    conn: sqlite3.Connection,
    json_path: str = "hacktoberfest_events.json",
    md_path: str = "hacktoberfest_schedule.md",
    tz_offset_hours: Optional[float] = None,
):
    """Export Hacktoberfest events to JSON and a formatted Markdown schedule."""
    if tz_offset_hours is None:
        tz_offset_hours = get_system_tz_offset()

    cursor = conn.cursor()
    cursor.execute("""
        SELECT raw_json FROM events
        WHERE is_hacktoberfest = 1
        ORDER BY start_date_utc ASC
    """)
    rows = cursor.fetchall()
    events = [json.loads(r[0]) for r in rows]

    tz_label = get_tz_label(tz_offset_hours)
    now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=tz_offset_hours)))
    for ev in events:
        _, start_local_str = utc_to_local(ev.get("start_date_utc"), tz_offset_hours)
        if start_local_str:
            ev["start_date_local"] = start_local_str
        _, end_local_str = utc_to_local(ev.get("end_date_utc"), tz_offset_hours)
        if end_local_str:
            ev["end_date_local"] = end_local_str
        ev["status"] = get_event_status(ev.get("start_date_utc"), ev.get("end_date_utc"), current_time=now, tz_offset_hours=tz_offset_hours)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2, ensure_ascii=False)
    logger.info(f"Exported {len(events)} Hacktoberfest events to {json_path}")

    # Generate Markdown schedule
    upcoming = [e for e in events if e["status"] == "UPCOMING" and not e.get("is_test")]
    live = [e for e in events if e["status"] == "LIVE" and not e.get("is_test")]
    completed = [e for e in events if e["status"] == "COMPLETED" and not e.get("is_test")]
    tests = [e for e in events if e.get("is_test")]

    lines = [
        "# Hacktoberfest 2026 Event Tracker & Schedule (MLH)",
        f"*Generated on: {now.strftime(f'%Y-%m-%d %H:%M:%S {tz_label}')} | Timezone: {tz_label}*",
        "",
        "## Summary",
        f"- **Total Hacktoberfest Events**: {len(events)}",
        f"- **Live Right Now**: {len(live)}",
        f"- **Upcoming (Yet to be held)**: {len(upcoming)}",
        f"- **Completed**: {len(completed)}",
        f"- **Test Events**: {len(tests)}",
        "",
    ]

    def render_event_table(event_list: List[Dict[str, Any]], title: str) -> List[str]:
        out = [f"## {title} ({len(event_list)})", ""]
        if not event_list:
            out.append("*None at this time.*")
            out.append("")
            return out

        out.append(f"| ID | Start ({tz_label}) | Title | Series | Type | Event Page & Calendar |")
        out.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for e in event_list:
            eid = e["event_id"]
            start_str = e.get("start_date_local") or "TBA"
            t = e.get("title", "Untitled")
            s = e.get("series", "—")
            ltype = e.get("location_type", "Virtual")
            event_url = e.get("url") or f"{BASE_URL}/events/{eid}"
            ics_url = e.get("calendar_links", {}).get("ics", "")
            ics_badge = f" [ICS]({ics_url})" if ics_url else ""
            out.append(f"| **{eid}** | `{start_str}` | **{t}** | {s} | {ltype} | [Open Event]({event_url}){ics_badge} |")
        out.append("")
        return out

    lines.extend(render_event_table(live, "🔴 Live Now"))
    lines.extend(render_event_table(upcoming, "⏳ Upcoming Events (Yet to be Held)"))
    lines.extend(render_event_table(completed, "✅ Completed Events"))

    if tests:
        lines.extend(render_event_table(tests, "🧪 Test Events (Filtered)"))

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"Exported formatted schedule to {md_path}")


# --- Parallel Scraping Orchestration ---

def scrape_worker(
    event_id: int,
    session: requests.Session,
    tz_offset_hours: Optional[float] = None,
) -> Tuple[int, int, Optional[Dict[str, Any]]]:
    """Single worker unit to fetch and parse an event ID."""
    status_code, html = fetch_event_html(event_id, session=session)
    if status_code == 200 and html:
        try:
            event_data = parse_event(html, event_id, tz_offset_hours=tz_offset_hours)
            return event_id, 200, event_data
        except Exception as e:
            logger.error(f"Error parsing event {event_id}: {e}")
            return event_id, 500, None
    return event_id, status_code, None


def run_scraper(
    start_id: int = 14620,
    end_id: int = 15600,
    max_workers: int = 5,
    tz_offset_hours: Optional[float] = None,
    db_path: str = "events.db",
    json_path: str = "hacktoberfest_events.json",
    md_path: str = "hacktoberfest_schedule.md",
    force_rescrape: bool = False,
):
    """Run multithreaded scraper across event ID range."""
    if tz_offset_hours is None:
        tz_offset_hours = get_system_tz_offset()

    conn = init_db(db_path)
    checked_ids = set() if force_rescrape else get_checked_ids(conn)

    ids_to_scrape = [eid for eid in range(start_id, end_id + 1) if eid not in checked_ids]
    logger.info(f"Total range: {start_id}..{end_id} ({end_id - start_id + 1} IDs).")
    logger.info(f"Already checked: {len(checked_ids)} IDs. Remaining to fetch: {len(ids_to_scrape)} IDs.")

    if not ids_to_scrape:
        logger.info("All IDs in range have already been fetched. Exporting datasets...")
        export_dataset(conn, json_path=json_path, md_path=md_path, tz_offset_hours=tz_offset_hours)
        return

    # Use thread-local sessions
    session = requests.Session()

    completed_count = 0
    hf_found_count = 0
    total = len(ids_to_scrape)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_id = {
            executor.submit(scrape_worker, eid, session, tz_offset_hours): eid
            for eid in ids_to_scrape
        }

        for future in concurrent.futures.as_completed(future_to_id):
            completed_count += 1
            eid, status_code, event_data = future.result()

            record_checked_id(conn, eid, status_code)
            if status_code == 200 and event_data:
                save_event_to_db(conn, event_data)
                if event_data.get("is_hacktoberfest"):
                    hf_found_count += 1
                    status_badge = event_data.get("status")
                    logger.info(
                        f"[{completed_count}/{total}] Event {eid}: "
                        f"[{event_data.get('location_type')}] {event_data.get('title')} ({status_badge})"
                    )
            elif completed_count % 50 == 0 or completed_count == total:
                logger.info(f"Progress: {completed_count}/{total} IDs processed ({hf_found_count} Hacktoberfest events found so far).")

    logger.info("Scraping completed! Generating output files...")
    export_dataset(conn, json_path=json_path, md_path=md_path, tz_offset_hours=tz_offset_hours)


def update_events(
    max_consecutive_404: int = 25,
    refresh_tba: bool = True,
    refresh_upcoming: bool = False,
    tz_offset_hours: Optional[float] = None,
    db_path: str = "events.db",
    json_path: str = "hacktoberfest_events.json",
    md_path: str = "hacktoberfest_schedule.md",
) -> int:
    """
    Check for newly added events on a rolling basis and refresh existing TBA/upcoming events.
    1. Re-fetches events marked with TBA/TBD or upcoming to capture updated schedules/venues.
    2. Probes upwards from the highest existing ID in the database until max_consecutive_404
       non-existent IDs are reached.
    """
    if tz_offset_hours is None:
        tz_offset_hours = get_system_tz_offset()

    conn = init_db(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(event_id) FROM checked_ids")
    row = cursor.fetchone()
    current_max_id = row[0] if (row and row[0]) else None

    if current_max_id is None and os.path.exists(json_path):
        logger.info(f"Bootstrapping database from {json_path}...")
        with open(json_path, "r", encoding="utf-8") as f:
            cached = json.load(f)
        for ev in cached:
            save_event_to_db(conn, ev)
            record_checked_id(conn, ev["event_id"], 200)
        current_max_id = max(e["event_id"] for e in cached)

    if current_max_id is None:
        current_max_id = 14619

    session = requests.Session()

    # Refresh TBA or upcoming events if requested
    if refresh_tba or refresh_upcoming:
        if refresh_upcoming:
            cursor.execute("""
                SELECT event_id FROM events
                WHERE is_hacktoberfest = 1
                  AND (status = 'UPCOMING' OR venue_name LIKE '%TBA%' OR venue_name LIKE '%TBD%')
            """)
        else:
            cursor.execute("""
                SELECT event_id FROM events
                WHERE is_hacktoberfest = 1
                  AND (venue_name LIKE '%TBA%' OR venue_name LIKE '%TBD%' OR start_date_utc IS NULL OR start_date_utc = '')
            """)
        refresh_ids = [r[0] for r in cursor.fetchall()]
        if refresh_ids:
            logger.info(f"Checking {len(refresh_ids)} events with TBA/upcoming status for updates...")
            for rid in refresh_ids:
                status_code, html = fetch_event_html(rid, session=session)
                if status_code == 200 and html:
                    try:
                        ev = parse_event(html, rid, tz_offset_hours=tz_offset_hours)
                        save_event_to_db(conn, ev)
                    except Exception as e:
                        logger.error(f"Error refreshing event {rid}: {e}")

    # Probe upwards for new event IDs
    logger.info(f"Checking for new events starting from ID {current_max_id + 1}...")

    current_id = current_max_id + 1
    consecutive_404s = 0
    newly_found = 0
    new_hf_events = 0

    while consecutive_404s < max_consecutive_404:
        status_code, html = fetch_event_html(current_id, session=session)
        record_checked_id(conn, current_id, status_code)

        if status_code == 200 and html:
            consecutive_404s = 0
            newly_found += 1
            try:
                ev = parse_event(html, current_id, tz_offset_hours=tz_offset_hours)
                save_event_to_db(conn, ev)
                if ev.get("is_hacktoberfest"):
                    new_hf_events += 1
                    logger.info(f"✨ Found new Hacktoberfest event {current_id}: {ev.get('title')} ({ev.get('start_date_local')})")
            except Exception as e:
                logger.error(f"Error parsing event {current_id}: {e}")
        elif status_code == 404:
            consecutive_404s += 1
        else:
            consecutive_404s += 1

        current_id += 1
        time.sleep(0.1)

    logger.info(f"Update check finished. Scanned up to ID {current_id - 1}. Found {newly_found} new events ({new_hf_events} Hacktoberfest).")
    export_dataset(conn, json_path=json_path, md_path=md_path, tz_offset_hours=tz_offset_hours)
    return new_hf_events


def main():
    parser = argparse.ArgumentParser(description="Scrape and manage MLH Hacktoberfest 2026 events.")
    parser.add_argument("--start", type=int, default=14620, help="Start event ID (default: 14620)")
    parser.add_argument("--end", type=int, default=15600, help="End event ID (default: 15600)")
    parser.add_argument("--workers", "-w", type=int, default=5, help="Concurrent workers (default: 5)")
    parser.add_argument("--tz", type=float, default=None, help="Local timezone offset in hours (default: auto-detected host timezone)")
    parser.add_argument("--db", type=str, default="events.db", help="SQLite database path")
    parser.add_argument("--json", type=str, default="hacktoberfest_events.json", help="Output JSON path")
    parser.add_argument("--md", type=str, default="hacktoberfest_schedule.md", help="Output Markdown schedule path")
    parser.add_argument("--force", action="store_true", help="Force re-scraping of already fetched IDs")
    parser.add_argument("--export-only", action="store_true", help="Only re-export datasets from database")
    parser.add_argument("--update", "-u", action="store_true", help="Probe upwards from max existing ID for newly added rolling events")
    parser.add_argument("--refresh-upcoming", action="store_true", help="Re-fetch and refresh all upcoming events during update")
    parser.add_argument("--no-refresh-tba", action="store_true", help="Skip refreshing TBA/TBD events during update")
    args = parser.parse_args()

    tz_offset = args.tz if args.tz is not None else get_system_tz_offset()

    if args.update:
        update_events(
            refresh_tba=not args.no_refresh_tba,
            refresh_upcoming=args.refresh_upcoming,
            tz_offset_hours=tz_offset,
            db_path=args.db,
            json_path=args.json,
            md_path=args.md,
        )
        return

    if args.export_only:
        conn = init_db(args.db)
        export_dataset(conn, json_path=args.json, md_path=args.md, tz_offset_hours=tz_offset)
        return

    run_scraper(
        start_id=args.start,
        end_id=args.end,
        max_workers=args.workers,
        tz_offset_hours=tz_offset,
        db_path=args.db,
        json_path=args.json,
        md_path=args.md,
        force_rescrape=args.force,
    )


if __name__ == "__main__":
    main()
