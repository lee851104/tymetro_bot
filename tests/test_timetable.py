import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.fetch_timetable import fetch
from src.timetable import DEFAULT_CACHE, ParseError, add_page, parse_timetable, pattern_id, query_departures


def fixture(station="A8", service_date="2026-09-21"):
    """Small synthetic data with the live site's accessible/visual markup."""
    def table(direction):
        rows = []
        for hour in list(range(5, 24)) + [0, 1]:
            cell = '<td colspan="8">目前無班次</td>'
            if direction == "up" and hour in {10, 23, 0}:
                minute = "05" if hour != 23 else "58"
                code = "des01" if hour == 10 else "des03"
                cell = (f'<td><div class="sr-only">{hour:02d}點</div>'
                        f'<span class="downspan {code}"><i>{minute}</i></span>'
                        '<div class="sr-only">一般-普通車(每站停靠)</div></td>')
            rows.append(f'<tr><th scope="row">{hour:02d}</th>{cell}</tr>')
        return (f'<table class="time-table" summary="桃園捷運列車時刻表:往台北車站">'
                f'<caption>長庚醫院站 時刻表 : {station} 長庚醫院站</caption>'
                f'<tbody class="{direction}">{"".join(rows)}</tbody></table>')
    return (f'<input id="timetable_date" value="{service_date}">'
            f'<a href="timetable-{station}">{station} 長庚醫院站</a>'
            '<!-- <div style="color:red;">＊目前時刻表更新至112/1/1</div> -->'
            '<div style="color:red;">＊目前時刻表更新至115/10/31</div>'
            '<div class="time-description"><ul>'
            '<li><span class="des01"><i>00</i></span>加底線-直達車</li>'
            '<li><span class="des03"><i>00</i></span>一般-普通車</li>'
            '</ul></div>' + table("up") + table("down") + table("up") + table("down"))


class TimetableParserTests(unittest.TestCase):
    def test_deduplicates_accessible_and_visual_tables_and_preserves_midnight(self):
        page = parse_timetable(fixture(), "A8", "2026-09-21")
        rows = page["directions"]["up"]["departures"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[-1], {"time": "00:05", "day_offset": 1, "service_code": "des03"})
        self.assertEqual(rows[0]["service_code"], "des01")
        self.assertEqual(page["directions"]["down"]["departures"], [])
        self.assertEqual(page["published_through"], "2026-10-31")

    def test_rejects_wrong_date_station_and_date_beyond_official_horizon(self):
        for html, station, day in [(fixture(), "A8", "2026-09-22"),
                                    (fixture(), "A9", "2026-09-21"),
                                    (fixture(service_date="2026-11-01"), "A8", "2026-11-01")]:
            with self.subTest(station=station, day=day), self.assertRaises(ParseError):
                parse_timetable(html, station, day)

    def test_fails_closed_on_unknown_service_or_incomplete_table(self):
        for html in [fixture().replace('downspan des01', 'downspan des99'),
                     fixture().replace('<th scope="row">05</th>', '<th scope="row">06</th>'),
                     '<html>temporarily unavailable</html>']:
            with self.subTest(html=html[:50]), self.assertRaises(ParseError):
                parse_timetable(html, "A8", "2026-09-21")

    def test_rejects_disagreement_between_duplicate_tables(self):
        html = fixture().replace('<i>58</i>', '<i>57</i>', 1)
        with self.assertRaisesRegex(ParseError, "disagree"):
            parse_timetable(html, "A8", "2026-09-21")


class OfflineTimetableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "cache.json"
        self.cache = {"schema_version": 1, "source_type": "scheduled",
                      "stations": {}, "patterns": {}, "calendar": {}}
        for day in ["2026-09-21", "2026-09-22"]:
            add_page(self.cache, parse_timetable(fixture(service_date=day), "A8", day),
                     "2026-09-01T10:00:00+08:00", "test-source-hash")
        self.path.write_text(json.dumps(self.cache), encoding="utf-8")

    def query(self, at, direction="up"):
        return query_departures("A8", direction, at, self.path)

    def test_same_pattern_is_shared_between_dates(self):
        self.assertEqual(len(self.cache["patterns"]), 1)
        self.assertEqual(len(self.cache["calendar"]), 2)

    def test_next_two_are_read_offline_even_when_fetch_is_older_than_15_minutes(self):
        with patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("network forbidden")):
            result = self.query("2026-09-21T10:00:00+08:00")
        self.assertEqual(result["status"], "ok")
        self.assertEqual([item["departure"] for item in result["next_departures"]],
                         ["2026-09-21T10:05:00+08:00", "2026-09-21T23:58:00+08:00"])
        self.assertEqual(result["source_type"], "scheduled")
        self.assertEqual(result["service_status"], "unknown")
        self.assertFalse(result["live_disruptions_checked"])

    def test_midnight_queries_previous_service_date_in_taiwan_time(self):
        result = self.query("2026-09-21T16:01:00+00:00")
        self.assertEqual(result["service_date"], "2026-09-21")
        self.assertEqual(result["next_departures"][0]["departure"], "2026-09-22T00:05:00+08:00")
        self.assertEqual(result["remaining_departures"], 1)

    def test_uncached_date_is_not_reported_as_no_service_or_replaced_by_weekday(self):
        result = self.query("2026-09-28T10:00:00+08:00")
        self.assertEqual(result["status"], "date_not_cached")
        self.assertEqual(result["next_departures"], [])

    def test_no_trains_remaining_does_not_claim_suspension(self):
        result = self.query("2026-09-22T00:06:00+08:00")
        self.assertEqual(result["status"], "no_departures_remaining")
        self.assertEqual(result["service_status"], "unknown")

    def test_invalid_inputs_and_modified_pattern_are_rejected(self):
        with self.assertRaises(ValueError):
            self.query("2026-09-21T10:00:00")
        pattern = next(iter(self.cache["patterns"].values()))
        pattern["directions"]["up"]["departures"][0]["time"] = "11:00"
        self.path.write_text(json.dumps(self.cache), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.query("2026-09-21T10:00:00+08:00")


class DownloadAndSnapshotTests(unittest.TestCase):
    def test_each_request_keeps_its_date_when_server_preference_cookie_expires(self):
        from unittest.mock import MagicMock

        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = b"page"
        self.assertEqual(fetch(opener, "https://example.test/timetable-A8",
                               service_date="2026-09-26"), "page")
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_header("Cookie"), "tymetro_new_chdate=2026-09-26")

    def test_saved_snapshot_contains_complete_station_days_and_intact_patterns(self):
        cache = json.loads(DEFAULT_CACHE.read_text(encoding="utf-8"))
        self.assertEqual(cache["source_type"], "scheduled")
        self.assertEqual(len(cache["stations"]), 22)
        self.assertIn("A14a", cache["stations"])
        self.assertTrue(cache["calendar"])
        for day, stations in cache["calendar"].items():
            self.assertEqual(set(stations), set(cache["stations"]), day)
            for station, entry in stations.items():
                self.assertLessEqual(day, entry["published_through"])
                pattern = cache["patterns"][entry["pattern_id"]]
                self.assertEqual(pattern["station_id"], station)
                self.assertEqual(pattern_id(pattern), entry["pattern_id"])
                self.assertEqual(set(pattern["directions"]), {"up", "down"})


if __name__ == "__main__":
    unittest.main()
