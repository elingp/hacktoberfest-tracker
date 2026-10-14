import unittest
from datetime import datetime, timezone, timedelta
from scraper import parse_event, classify_event, utc_to_local, get_event_status

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

    def test_timezone_conversion(self):
        # 17:00:00 UTC -> 01:00:00 next day UTC+8
        dt_local, local_str = utc_to_local("2026-10-14 17:00:00 UTC", tz_offset_hours=8)
        self.assertEqual(dt_local.year, 2026)
        self.assertEqual(dt_local.month, 10)
        self.assertEqual(dt_local.day, 15)
        self.assertEqual(dt_local.hour, 1)
        self.assertEqual(dt_local.minute, 0)
        self.assertIn("2026-10-15 01:00:00 UTC+08:00", local_str)

    def test_event_status(self):
        tz_plus_8 = timezone(timedelta(hours=8))
        ref_time = datetime(2026, 10, 15, 0, 0, 0, tzinfo=tz_plus_8)

        # Event in the future (starts at 01:00)
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

    def test_classify_event(self):
        # Explicit Hacktoberfest series
        is_hf, is_test = classify_event("Hackathon Day", "Hacktoberfest 2026")
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

        # Test event
        is_hf, is_test = classify_event("Stephen Test Hacktoberfest", "Hacktoberfest 2026")
        self.assertTrue(is_hf)
        self.assertTrue(is_test)

        # Unrelated event
        is_hf, is_test = classify_event("Intro to SQL", "GHW Data week")
        self.assertFalse(is_hf)

if __name__ == "__main__":
    unittest.main()
