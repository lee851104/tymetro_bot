import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.station_routes import (DEFAULT_RULES, load_service_rules, resolve_station,
                                route_for_service)
from src.timetable import (DEFAULT_CACHE, add_page, format_timetable_result,
                           query_direct_trains)


class DirectTrainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "cache.json"
        self.rules_path = Path(self.temp.name) / "rules.json"
        self.rules = json.loads(DEFAULT_RULES.read_text(encoding="utf-8"))
        self.rules_path.write_text(json.dumps(self.rules), encoding="utf-8")
        snapshot = json.loads(DEFAULT_CACHE.read_text(encoding="utf-8"))
        self.stations = snapshot["stations"]
        self.cache = {"schema_version": 1, "source_type": "scheduled",
                      "stations": self.stations, "patterns": {}, "calendar": {}}
        self.schedules = {
            "A8": {"down": [("10:00", "des01"), ("10:01", "des02"),
                               ("10:02", "des06"), ("10:03", "des04"),
                               ("10:04", "des03"), ("10:05", "des03")],
                   "up": [("07:41", "des05")]},
            "A22": {"up": [("23:50", "des04"), ("00:05", "des04")]},
            "A21": {"up": [("07:00", "des05"), ("07:05", "des03")]},
            "A13": {"up": [("10:00", "des07"), ("10:03", "des03")],
                    "down": [("10:00", "des03")]},
            "A14a": {"up": [("10:00", "des03")]},
        }
        self.write_cache()

    def write_cache(self, legend_override=None):
        for station, directions in self.schedules.items():
            tables = {}
            for direction in ("up", "down"):
                tables[direction] = {"label": direction, "source_notes": {}, "departures": [
                    {"time": at, "service_code": code, "day_offset": int(at < "03:00")}
                    for at, code in directions.get(direction, [])]}
            legends = {code: rule["source_legend"] for code, rule in self.rules["services"].items()}
            legends.update(legend_override or {})
            add_page(self.cache, {"station_id": station, "station_name": self.stations[station],
                                 "stations": self.stations, "service_date": "2026-09-26",
                                 "published_through": "2026-10-31", "notices": [],
                                 "directions": tables, "legends": legends},
                     "2026-09-21T10:00:00+08:00", "fixture")
        self.path.write_text(json.dumps(self.cache), encoding="utf-8")

    def query(self, origin, destination, at="2026-09-26T10:00:00+08:00"):
        # These fixtures isolate route filtering; boarding policy has separate tests.
        return query_direct_trains(origin, destination, at, self.path, rules_path=self.rules_path,
                                   boarding_buffer_minutes=0)

    def test_filters_nonstopping_trains_before_taking_the_next_two(self):
        result = self.query("A8", "A10")
        self.assertEqual([item["departure"][11:16] for item in result["next_departures"]],
                         ["10:02", "10:03"])
        self.assertEqual(result["remaining_departures"], 4)
        self.assertEqual(result["direction"], "down")
        self.assertEqual(result["next_departures"][0]["stops_to_destination"], ["A8", "A9", "A10"])

    def test_short_turns_and_extended_express_do_not_reach_a22(self):
        result = self.query("A8", "A22")
        self.assertEqual([item["departure"][11:16] for item in result["next_departures"]],
                         ["10:04", "10:05"])
        self.assertEqual({item["terminal_station_id"] for item in result["next_departures"]}, {"A22"})

    def test_extended_express_reaches_a21_but_airport_express_does_not(self):
        result = self.query("A8", "A21")
        self.assertEqual([item["service_code"] for item in result["next_departures"]],
                         ["des02", "des06"])

    def test_northbound_airport_extra_terminates_at_a12_across_midnight(self):
        result = self.query("A22", "A12", "2026-09-26T23:40:00+08:00")
        self.assertEqual(result["next_departures"][1]["departure"], "2026-09-27T00:05:00+08:00")
        self.assertEqual(result["next_departures"][1]["terminal_station_id"], "A12")
        after_midnight = self.query("A22", "A12", "2026-09-27T00:01:00+08:00")
        self.assertEqual(after_midnight["remaining_departures"], 1)
        self.assertIn("後面沒有下一班", format_timetable_result(after_midnight))
        no_direct = self.query("A22", "A1", "2026-09-26T23:40:00+08:00")
        self.assertEqual(no_direct["status"], "no_direct_departures_remaining")
        self.assertEqual(no_direct["service_status"], "unknown")
        self.assertIn("轉乘方案尚未計算", format_timetable_result(no_direct))

    def test_skip_stop_local_stops_at_a9_and_a6_but_skips_a10(self):
        at = "2026-09-26T06:55:00+08:00"
        self.assertEqual(self.query("A21", "A9", at)["next_departures"][0]["service_code"], "des05")
        self.assertEqual(self.query("A21", "A10", at)["next_departures"][0]["service_code"], "des03")
        self.assertEqual(self.query("A8", "A6", at)["next_departures"][0]["service_code"], "des05")

    def test_event_shuttle_is_excluded_for_destinations_north_of_a12(self):
        result = self.query("A13", "A1")
        self.assertEqual(result["remaining_departures"], 1)
        self.assertEqual(result["next_departures"][0]["service_code"], "des03")

    def test_station_names_and_a14a_follow_physical_station_order(self):
        result = self.query("長庚醫院", "山鼻站")
        self.assertEqual(result["station_id"], "A8")
        self.assertEqual(result["destination_id"], "A10")
        self.assertEqual(resolve_station("臺北車站", self.stations), "A1")
        self.assertEqual(self.query("a14A", "A13")["direction"], "up")
        self.assertEqual(self.query("A13", "A14a")["direction"], "down")
        with self.assertRaises(ValueError):
            self.query("A23", "A1")

    def test_unknown_or_changed_rules_never_fall_back_to_ordinary_train(self):
        self.write_cache({"des01": "直達車停靠規則已改變"})
        result = self.query("A8", "A10")
        self.assertEqual(result["status"], "service_rules_unavailable")
        self.assertEqual(result["next_departures"], [])
        self.assertTrue(result["rule_errors"])

    def test_invalid_rule_period_and_changed_station_list_require_review(self):
        self.rules["services"]["des06"]["valid_through"] = "2026-09-25"
        self.rules_path.write_text(json.dumps(self.rules), encoding="utf-8")
        self.assertEqual(self.query("A8", "A10")["status"], "service_rules_unavailable")
        self.rules["station_order"].append("A23")
        self.rules_path.write_text(json.dumps(self.rules), encoding="utf-8")
        self.assertEqual(self.query("A8", "A10")["status"], "service_rules_unavailable")

    def test_missing_date_same_station_and_no_fabricated_arrival(self):
        self.assertEqual(self.query("A8", "A10", "2026-09-28T10:00:00+08:00")["status"],
                         "date_not_cached")
        self.assertEqual(self.query("A8", "長庚醫院")["status"], "same_station")
        with patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("network forbidden")):
            result = self.query("A8", "A10")
        self.assertTrue(all(item["arrival"] is None for item in result["next_departures"]))
        self.assertFalse(result["arrival_time_available"])
        self.assertFalse(result["live_disruptions_checked"])
        self.assertIn("目前沒有抵達時間資料", format_timetable_result(result))


class SavedStopRuleTests(unittest.TestCase):
    def test_every_saved_service_agrees_with_reviewed_rule_and_origin(self):
        cache = json.loads(DEFAULT_CACHE.read_text(encoding="utf-8"))
        rules = load_service_rules(cache["stations"])
        for day, stations in cache["calendar"].items():
            for station, entry in stations.items():
                pattern = cache["patterns"][entry["pattern_id"]]
                for direction, table in pattern["directions"].items():
                    for code in {row["service_code"] for row in table["departures"]}:
                        with self.subTest(day=day, station=station, direction=direction, code=code):
                            stops = route_for_service(rules, code, pattern["legends"][code], direction, day)
                            self.assertIn(station, stops[:-1])


if __name__ == "__main__":
    unittest.main()
