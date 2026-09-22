import copy
import json
import unittest
from datetime import date
from pathlib import Path

from scripts.build_normal_timetable import build_cache
from src.service_calendar import classify_service_date, expand_calendar
from src.timetable import DEFAULT_CACHE, query_departures, query_direct_trains

ROOT = Path(__file__).resolve().parents[1]


class CalendarPolicyTests(unittest.TestCase):
    def test_published_holidays_and_unprovided_year(self):
        for day in ("2026-02-27", "2026-04-03", "2026-04-06", "2026-09-25",
                    "2026-09-28", "2026-10-09", "2026-10-26", "2026-12-25"):
            self.assertEqual(classify_service_date(day), "holiday", day)
        self.assertEqual(classify_service_date("2026-09-21"), "workday")
        self.assertEqual(classify_service_date("2026-09-26"), "holiday")
        with self.assertRaises(ValueError):
            classify_service_date("2027-01-01")
        calendar = json.loads((ROOT / "data/timetable/calendar_2026.json").read_text(encoding="utf-8"))
        self.assertEqual(len(calendar["dates"]), 365)
        self.assertEqual(sum(d["day_type"] == "holiday" for d in calendar["dates"].values()), 120)

    def test_makeup_workday_overrides_weekend_and_conflicts_fail(self):
        rules = json.loads((ROOT / "data/timetable/sources/dgpa_2026_rules.json").read_text(encoding="utf-8"))
        rules["working_day_overrides"]["2026-09-26"] = "synthetic test only"
        self.assertEqual(expand_calendar(rules)["dates"]["2026-09-26"]["day_type"], "workday")
        rules["extra_holidays"]["2026-09-26"] = "conflict"
        with self.assertRaises(ValueError):
            expand_calendar(rules)

    def test_activity_dates_use_complete_normal_patterns(self):
        cache = json.loads(DEFAULT_CACHE.read_text(encoding="utf-8"))
        for day, entries in cache["calendar"].items():
            self.assertEqual(len(entries), 22)
            for entry in entries.values():
                self.assertEqual(entry["day_type"], classify_service_date(day))
                self.assertFalse(entry["special_events_included"])
                pattern = cache["patterns"][entry["pattern_id"]]
                self.assertFalse({"des06", "des07"} & set(pattern["legends"]))
                for table in pattern["directions"].values():
                    self.assertFalse(any(r["service_code"] in {"des06", "des07"} for r in table["departures"]))
        weekday = query_direct_trains("A1", "A21", "2026-09-24T15:56:00+08:00")
        self.assertEqual(weekday["next_departures"][0]["service_code"], "des02")
        holiday = query_departures("A1", "down", "2026-09-28T13:00:00+08:00", limit=100)
        self.assertEqual(holiday["day_type"], "holiday")
        self.assertEqual(holiday["next_departures"][0]["service_code"], "des02")
        self.assertNotIn("18:04", [r["departure"][11:16] for r in holiday["next_departures"]])

    def test_reviewed_skip_train_and_holiday_1354(self):
        skip = query_departures("A21", "up", "2026-09-21T07:00:00+08:00")
        self.assertEqual(skip["next_departures"][0]["service_code"], "des05")
        a18 = query_departures("A18", "down", "2026-09-25T13:50:00+08:00")
        self.assertEqual(a18["next_departures"][0]["departure"][11:16], "13:54")
        self.assertEqual(a18["next_departures"][0]["service_code"], "des02")

    def test_night_adjustment_is_not_applied_twice_and_midnight_uses_service_day(self):
        expected = {"A10":"22:07", "A11":"22:10", "A12":"22:14", "A13":"22:17",
                    "A14a":"22:20", "A15":"22:23", "A16":"22:26", "A17":"22:29"}
        for station, at in expected.items():
            result = query_departures(station, "down", "2026-09-21T22:00:01+08:00", limit=100)
            locals_ = [r["departure"][11:16] for r in result["next_departures"] if r["service_code"] == "des03"]
            self.assertIn(at, locals_, station)
        result = query_departures("A3", "up", "2026-09-25T00:05:00+08:00")
        self.assertEqual(result["service_date"], "2026-09-24")
        self.assertEqual(result["day_type"], "workday")
        self.assertTrue(all(r["departure"].startswith("2026-09-25") for r in result["next_departures"]))

    def test_builder_rejects_activity_reference_and_expired_horizon(self):
        weekday = json.loads((ROOT / "data/timetable/official_cache.json").read_text(encoding="utf-8"))
        holiday = json.loads((ROOT / "data/timetable/sources/official_holiday_2026-10-17.json").read_text(encoding="utf-8"))
        calendar = json.loads((ROOT / "data/timetable/calendar_2026.json").read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ValueError, "publication horizon"):
            build_cache(weekday, holiday, calendar, date(2026, 11, 1), 1)
        bad = copy.deepcopy(holiday)
        entry = bad["calendar"]["2026-10-17"]["A12"]
        pattern = copy.deepcopy(bad["patterns"][entry["pattern_id"]])
        pattern["directions"]["down"]["departures"][0]["service_code"] = "des07"
        from src.timetable import pattern_id
        entry["pattern_id"] = pattern_id(pattern)
        bad["patterns"][entry["pattern_id"]] = pattern
        with self.assertRaisesRegex(ValueError, "special-event"):
            build_cache(weekday, bad, calendar, date(2026, 9, 25), 1)


if __name__ == "__main__":
    unittest.main()
