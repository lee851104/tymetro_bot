import json
import unittest

from src.bot_tools import get_next_trains, render_answer
from src.station_routes import resolve_station, StationClarificationRequired
from src.timetable import DEFAULT_CACHE, query_direct_trains, query_departures


class BoardingAndAliasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stations = json.loads(DEFAULT_CACHE.read_text(encoding="utf-8"))["stations"]

    def test_approved_aliases_and_deleted_or_ambiguous_names(self):
        for name, code in {"北車":"A1", "產業園區":"A3", "體大":"A7", "國體大":"A7",
                           "長庚林口":"A8", "林口長庚":"A8", "機捷桃園高鐵":"A18",
                           "T1":"A12", "Terminal 2":"A13", "機場旅館":"A14a"}.items():
            self.assertEqual(resolve_station(name, self.stations), code)
        with self.assertRaises(ValueError):
            resolve_station("新產", self.stations)
        for name in ("新莊", "青埔", "機場", "棒球那站", "A8 林口站", "A14a A13"):
            with self.subTest(name=name), self.assertRaises(StationClarificationRequired):
                resolve_station(name, self.stations)
        result = get_next_trains("A1", "青埔", "2026-09-21T10:00:00+08:00")
        self.assertEqual(result["status"], "station_needs_clarification")
        self.assertIn("青埔", render_answer(result))

    def test_same_minute_is_not_recommended_and_raw_table_is_unchanged(self):
        at = "2026-09-21T10:00:00+08:00"
        raw = query_departures("A1", "down", at)
        self.assertEqual(raw["next_departures"][0]["departure"][11:16], "10:00")
        result = get_next_trains("北車", "二航", at)
        self.assertEqual([t["departure"][11:16] for t in result["next_trains"]], ["10:08", "10:15"])
        self.assertEqual(result["imminent_departures"], [at])
        self.assertFalse(result["boarding_guaranteed"])
        self.assertIn("避免趕車或奔跑", render_answer(result))

    def test_exact_three_minutes_excluded_but_three_minutes_one_second_included(self):
        at = "2026-09-21T10:05:00+08:00"
        result = get_next_trains("A1", "A13", at)
        self.assertEqual(result["next_trains"][0]["departure"][11:16], "10:15")
        self.assertEqual(result["imminent_departures"][0][11:16], "10:08")
        earlier = get_next_trains("A1", "A13", "2026-09-21T10:04:59+08:00")
        self.assertEqual(earlier["next_trains"][0]["departure"][11:16], "10:08")

    def test_imminent_train_must_reach_destination(self):
        result = get_next_trains("A8", "A10", "2026-09-21T10:04:00+08:00")
        self.assertEqual(result["imminent_departures"], [])  # 10:07 express does not stop at A10.
        self.assertEqual(result["next_trains"][0]["departure"][11:16], "10:08")

    def test_last_train_does_not_invent_next_train(self):
        result = get_next_trains("A1", "A13", "2026-09-21T23:35:00+08:00")
        self.assertEqual(result["status"], "only_imminent_departures_remaining")
        self.assertEqual(result["next_trains"], [])
        self.assertIn("已無更晚", render_answer(result))
        self.assertNotIn("改搭上述", render_answer(result))

    def test_cutoff_crosses_midnight_without_switching_service_day(self):
        result = query_direct_trains("A13", "A12", "2026-09-21T23:59:00+08:00")
        self.assertEqual(result["service_date"], "2026-09-21")
        self.assertTrue(all(r["departure"] > "2026-09-22T00:02:00+08:00" for r in result["next_departures"]))


if __name__ == "__main__":
    unittest.main()
