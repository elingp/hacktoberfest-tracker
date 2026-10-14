from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
import unittest

# Ensure repo root is in sys.path so tests run with or without PYTHONPATH=.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper import parse_event, classify_event, utc_to_local, get_event_status, normalize_event_timing

SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head>
  <meta property="og:url" content="https://events.mlh.com/events/15572" />
  <meta property="og:title" content="Code for Good with DPGA and GitHub | Major League Hacking" />
  <meta property="og:image" content="https://example.com/banner.png" />
  <meta itemprop="startDate" content="2026-10-14 17:00:00 UTC" />
  <meta itemprop="endDate" content="2026-10-14 18:00:00 UTC" />
</head>
<body>
  <h1 itemprop="name">Code for Good with DPGA and GitHub</h1>
  <h4 class="text-mid-gray text-normal font-size-6 mt-1">Hacktoberfest 2026 Online</h4>
  <div itemprop="location" itemscope itemtype="https://schema.org/VirtualLocation">
    <div class="text-dark-gray text-semibold lh-title">Event is hosted online</div>
  </div>
  <div itemprop="description">
    <p>Event Description</p>
    <p>A virtual session with DPGA and GitHub.</p>
  </div>
  <a href="/events/15572-code-for-good/register">Register</a>
</body>
</html>
"""

SAMPLE_IN_PERSON_HTML = """
<!DOCTYPE html>
<html>
<head>
  <meta property="og:url" content="https://events.mlh.com/events/15121" />
  <meta property="og:title" content="Hacktoberfest Hack Day Pune | Major League Hacking" />
  <meta itemprop="startDate" content="2026-10-24 10:30:00 UTC" />
  <meta itemprop="endDate" content="2026-10-24 16:30:00 UTC" />
</head>
<body>
  <h1 itemprop="name">Hacktoberfest Hack Day Pune</h1>
  <h4 class="text-mid-gray text-normal font-size-6 mt-1">Hacktoberfest 2026</h4>
  <div itemprop="location" itemscope itemtype="https://schema.org/Place">
    <div itemprop="name">NST ADYPU Campus</div>
    <pre>Ajeenkya DY Patil University, Charholi Budruk, Pune, Maharashtra 412105</pre>
  </div>
  <div itemprop="description">
    <p>Event Description</p>
    <p>In-person hackathon in Pune.</p>
  </div>
</body>
</html>
"""

class TestScraper(unittest.TestCase):
    def test_parse_event(self):
        data = parse_event(SAMPLE_HTML, 15572)
        self.assertEqual(data["event_id"], 15572)
        self.assertEqual(data["title"], "Code for Good with DPGA and GitHub")
        self.assertEqual(data["series"], "Hacktoberfest 2026 Online")
        self.assertEqual(data["location_type"], "Virtual")
        self.assertEqual(data["start_date_utc"], "2026-10-14 17:00:00 UTC")
        self.assertEqual(data["end_date_utc"], "2026-10-14 18:00:00 UTC")
        self.assertIn("A virtual session with DPGA", data["description"])
        self.assertEqual(data["registration_url"], "https://events.mlh.com/events/15572-code-for-good/register")

    def test_parse_in_person_event(self):
        data = parse_event(SAMPLE_IN_PERSON_HTML, 15121)
        self.assertEqual(data["event_id"], 15121)
        self.assertEqual(data["title"], "Hacktoberfest Hack Day Pune")
        self.assertEqual(data["location_type"], "In-Person")
        self.assertEqual(data["venue_name"], "NST ADYPU Campus")
        self.assertIn("Ajeenkya DY Patil University", data["address"])

    def test_timezone_conversion(self):
        # UTC+8: 17:00:00 UTC -> 01:00:00 next day
        dt_local, local_str = utc_to_local("2026-10-14 17:00:00 UTC", tz_offset_hours=8)
        self.assertEqual(dt_local.year, 2026)
        self.assertEqual(dt_local.month, 10)
        self.assertEqual(dt_local.day, 15)
        self.assertEqual(dt_local.hour, 1)
        self.assertEqual(dt_local.minute, 0)
        self.assertIn("2026-10-15 01:00:00 UTC+08:00", local_str)

        # UTC-4 (US Eastern / EDT): 17:00:00 UTC -> 13:00:00 same day
        dt_edt, edt_str = utc_to_local("2026-10-14 17:00:00 UTC", tz_offset_hours=-4)
        self.assertEqual(dt_edt.day, 14)
        self.assertEqual(dt_edt.hour, 13)
        self.assertIn("2026-10-14 13:00:00 UTC-04:00", edt_str)

        # UTC+5.5 (India Standard Time / IST): 17:00:00 UTC -> 22:30:00 same day
        dt_ist, ist_str = utc_to_local("2026-10-14 17:00:00 UTC", tz_offset_hours=5.5)
        self.assertEqual(dt_ist.day, 14)
        self.assertEqual(dt_ist.hour, 22)
        self.assertEqual(dt_ist.minute, 30)
        self.assertIn("2026-10-14 22:30:00 UTC+05:30", ist_str)

        # ISO 8601 format with 'T' and 'Z'
        dt_iso, iso_str = utc_to_local("2026-10-14T17:00:00Z", tz_offset_hours=0)
        self.assertEqual(dt_iso.hour, 17)
        self.assertIn("2026-10-14 17:00:00 UTC+00:00", iso_str)

    def test_event_status(self):
        # Test under UTC+8 reference
        tz_plus_8 = timezone(timedelta(hours=8))
        ref_time = datetime(2026, 10, 15, 0, 0, 0, tzinfo=tz_plus_8)

        # Event in the future (starts at 01:00 UTC+8 / 17:00 UTC)
        status_future = get_event_status("2026-10-14 17:00:00 UTC", "2026-10-14 18:00:00 UTC", current_time=ref_time)
        self.assertEqual(status_future, "UPCOMING")

        # Event right now
        ref_time_live = datetime(2026, 10, 15, 1, 30, 0, tzinfo=tz_plus_8)
        status_live = get_event_status("2026-10-14 17:00:00 UTC", "2026-10-14 18:00:00 UTC", current_time=ref_time_live)
        self.assertEqual(status_live, "LIVE")

        # Event in the past
        ref_time_past = datetime(2026, 10, 15, 3, 0, 0, tzinfo=tz_plus_8)
        status_past = get_event_status("2026-10-14 17:00:00 UTC", "2026-10-14 18:00:00 UTC", current_time=ref_time_past)
        self.assertEqual(status_past, "COMPLETED")

        # Multi-day event whose start was 14 days ago (like event 14868)
        status_multiday_past = get_event_status("2026-10-01 06:30:00 UTC", "2026-10-31 06:30:00 UTC", current_time=ref_time_past)
        self.assertEqual(status_multiday_past, "COMPLETED")

        # Test under UTC-4 (US Eastern) reference
        tz_minus_4 = timezone(timedelta(hours=-4))
        ref_time_edt_upcoming = datetime(2026, 10, 14, 12, 0, 0, tzinfo=tz_minus_4)
        status_edt = get_event_status("2026-10-14 17:00:00 UTC", "2026-10-14 18:00:00 UTC", current_time=ref_time_edt_upcoming)
        self.assertEqual(status_edt, "UPCOMING")

        # Test with naive datetime (safeguard against naive vs aware comparison crash)
        ref_time_naive = datetime(2026, 10, 15, 3, 0, 0)
        status_naive = get_event_status("2026-10-14 17:00:00 UTC", "2026-10-14 18:00:00 UTC", current_time=ref_time_naive, tz_offset_hours=8)
        self.assertEqual(status_naive, "COMPLETED")

    def test_classify_event(self):
        # Explicit Hacktoberfest series
        is_hf, is_test = classify_event("Hackathon Day", "Hacktoberfest 2026")
        self.assertTrue(is_hf)
        self.assertFalse(is_test)

        # Non-test event containing substring 'test' like 'contest' or 'latest'
        is_hf, is_test = classify_event("Hacktoberfest Coding Contest", "Hacktoberfest 2026")
        self.assertTrue(is_hf)
        self.assertFalse(is_test)

        is_hf, is_test = classify_event("The Latest in Open Source", "Hacktoberfest 2026")
        self.assertTrue(is_hf)
        self.assertFalse(is_test)

        # GHW Hacktoberfest livestream
        is_hf, is_test = classify_event("[GHW Hacktoberfest] Opening Ceremony", "GHW: Livestream")
        self.assertTrue(is_hf)
        self.assertFalse(is_test)

        # Copilot session in October
        is_hf, is_test = classify_event("Hacking with GitHub Copilot @ BigRed", "Hacking with GitHub Copilot")
        self.assertTrue(is_hf)
        self.assertFalse(is_test)

        # Test event with word boundary
        is_hf, is_test = classify_event("Stephen Test Hacktoberfest", "Hacktoberfest 2026")
        self.assertTrue(is_hf)
        self.assertTrue(is_test)

        is_hf, is_test = classify_event("Hackathon tests session", "Hacktoberfest 2026")
        self.assertTrue(is_hf)
        self.assertTrue(is_test)

        # Unrelated event
        is_hf, is_test = classify_event("Intro to SQL", "GHW Data week")
        self.assertFalse(is_hf)

    def test_tui_helpers(self):
        from tui import get_event_page_url, format_countdown

        # Invariant 1: Ensure URL points to overview page, never ends with /register
        event_with_reg = {
            "event_id": 15572,
            "url": "https://events.mlh.com/events/15572-code-for-good/register",
        }
        self.assertEqual(get_event_page_url(event_with_reg), "https://events.mlh.com/events/15572-code-for-good")

        event_clean = {
            "event_id": 15572,
            "url": "https://events.mlh.com/events/15572-code-for-good",
        }
        self.assertEqual(get_event_page_url(event_clean), "https://events.mlh.com/events/15572-code-for-good")

        # Countdown formatting
        self.assertEqual(format_countdown(None), "TBA")
        self.assertEqual(format_countdown(""), "TBA")

    def test_normalize_event_timing(self):
        tz_offset = 8.0
        now = datetime(2026, 10, 15, 0, 0, 0, tzinfo=timezone(timedelta(hours=tz_offset)))
        ev = {
            "event_id": 100,
            "start_date_utc": "2026-10-14 17:00:00 UTC",
            "end_date_utc": "2026-10-14 18:00:00 UTC",
        }
        normalize_event_timing(ev, tz_offset_hours=tz_offset, current_time=now)
        self.assertIn("2026-10-15 01:00:00", ev["start_date_local"])
        self.assertIn("2026-10-15 02:00:00", ev["end_date_local"])
        self.assertEqual(ev["status"], "UPCOMING")

    def test_tui_filters(self):
        from tui import filter_today_events, filter_by_search

        tz_offset = 8.0
        now = datetime(2026, 10, 15, 0, 0, 0, tzinfo=timezone(timedelta(hours=tz_offset)))
        events = [
            # In 1 hour -> today
            {"event_id": 1, "title": "Copilot Workshop", "start_date_utc": "2026-10-14 17:00:00 UTC", "status": "UPCOMING"},
            # In 30 hours -> not today
            {"event_id": 2, "title": "Closing Ceremony", "start_date_utc": "2026-10-15 22:00:00 UTC", "status": "UPCOMING"},
            # Currently LIVE
            {"event_id": 3, "title": "Live Hackathon", "start_date_utc": "2026-10-14 15:00:00 UTC", "status": "LIVE"},
        ]

        today = filter_today_events(events, now, tz_offset)
        self.assertEqual([e["event_id"] for e in today], [1, 3])

        # Search across title
        results = filter_by_search(events, "copilot")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["event_id"], 1)

        # Search across venue_name or description
        events_extra = [
            {"event_id": 4, "title": "Meetup", "venue_name": "GitHub HQ", "description": "Fun times"},
        ]
        self.assertEqual(len(filter_by_search(events_extra, "github")), 1)
        self.assertEqual(len(filter_by_search(events_extra, "times")), 1)
        self.assertEqual(len(filter_by_search(events_extra, "nonexistent")), 0)

    def test_bootstrap_db_from_json(self):
        import json
        import os
        import tempfile
        from scraper import init_db, bootstrap_db_from_json

        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = os.path.join(tmpdir, "test.db")
            test_json = os.path.join(tmpdir, "test.json")
            events = [
                {"event_id": 99991, "title": "Test Event 1", "is_hacktoberfest": True},
                {"event_id": 99992, "title": "Test Event 2", "is_hacktoberfest": True},
            ]
            with open(test_json, "w", encoding="utf-8") as f:
                json.dump(events, f)
            conn = init_db(test_db)
            max_id = bootstrap_db_from_json(conn, test_json)
            conn.close()
            self.assertEqual(max_id, 99992)


if __name__ == "__main__":
    unittest.main()
