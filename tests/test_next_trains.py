import unittest

from src.schedule import get_next_trains


def leg(train, start, end, depart, arrive, stops, kind="普通車", status="normal"):
    return {
        "train_id": train,
        "origin": start,
        "destination": end,
        "departure": depart,
        "arrival": arrive,
        "stops": stops,
        "train_type": kind,
        "status": status,
    }


class NextTrainsTests(unittest.TestCase):
    def query(self, journeys, now="2099-01-01T10:00:00+08:00", fetched=None,
              source_type="scheduled"):
        return get_next_trains("A8", "A13", now, journeys,
                               fetched or now, source_type)

    def test_skips_train_that_does_not_stop_at_destination(self):
        journeys = [
            {"legs": [leg("E1", "A8", "A13", "2099-01-01T10:01:00+08:00",
                          "2099-01-01T10:30:00+08:00", ["A8", "A12"], "直達車")]},
            {"legs": [leg("C1", "A8", "A13", "2099-01-01T10:05:00+08:00",
                          "2099-01-01T10:40:00+08:00", ["A8", "A13"])]},
            {"legs": [leg("C2", "A8", "A13", "2099-01-01T10:15:00+08:00",
                          "2099-01-01T10:50:00+08:00", ["A8", "A13"])]},
        ]
        result = self.query(journeys)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["next_trains"][0]["legs"][0]["train_id"], "C1")
        self.assertEqual(result["next_trains"][1]["legs"][0]["train_id"], "C2")
        self.assertEqual(result["source_type"], "scheduled")
        self.assertIn("fetched_at", result)
        self.assertEqual(result["service_status"], "normal")
        self.assertIn("direction", result["next_trains"][0]["legs"][0])

    def test_cross_midnight_uses_full_date(self):
        journey = {"legs": [leg("N1", "A8", "A13", "2099-01-02T00:05:00+08:00",
                                "2099-01-02T00:40:00+08:00", ["A8", "A13"])]}
        result = self.query([journey], "2099-01-01T23:58:00+08:00")
        self.assertEqual(result["next_trains"][0]["departure"],
                         "2099-01-02T00:05:00+08:00")

    def test_last_train_gone_has_no_invented_time(self):
        journey = {"legs": [leg("L1", "A8", "A13", "2099-01-01T23:50:00+08:00",
                                "2099-01-02T00:20:00+08:00", ["A8", "A13"])]}
        result = self.query([journey], "2099-01-01T23:58:00+08:00")
        self.assertEqual(result["status"], "no_service")
        self.assertEqual(result["next_trains"], [])

    def test_delay_uses_updated_time_and_cancellation_is_excluded(self):
        cancelled = leg("X", "A8", "A13", "2099-01-01T10:02:00+08:00",
                        "2099-01-01T10:32:00+08:00", ["A8", "A13"], status="cancelled")
        delayed = leg("D", "A8", "A13", "2099-01-01T10:04:00+08:00",
                      "2099-01-01T10:34:00+08:00", ["A8", "A13"], status="delayed")
        delayed["updated_departure"] = "2099-01-01T10:12:00+08:00"
        result = self.query([{"legs": [cancelled]}, {"legs": [delayed]}],
                            source_type="realtime")
        self.assertEqual(result["next_trains"][0]["departure"],
                         "2099-01-01T10:12:00+08:00")
        self.assertEqual(len(result["next_trains"]), 1)
        self.assertEqual(result["service_status"], "delayed")

    def test_transfer_wait_and_arrival_are_checked(self):
        bad = {"legs": [
            leg("T1", "A8", "A12", "2099-01-01T10:05:00+08:00",
                "2099-01-01T10:20:00+08:00", ["A8", "A12"]),
            leg("T2", "A12", "A13", "2099-01-01T10:19:00+08:00",
                "2099-01-01T10:25:00+08:00", ["A12", "A13"]),
        ]}
        good = {"legs": [
            leg("T3", "A8", "A12", "2099-01-01T10:06:00+08:00",
                "2099-01-01T10:22:00+08:00", ["A8", "A12"]),
            leg("T4", "A12", "A13", "2099-01-01T10:28:00+08:00",
                "2099-01-01T10:35:00+08:00", ["A12", "A13"]),
        ]}
        result = self.query([bad, good])
        self.assertEqual(result["next_trains"][0]["arrival"],
                         "2099-01-01T10:35:00+08:00")
        self.assertEqual(result["next_trains"][0]["transfer_wait_minutes"], 6)
        self.assertEqual(result["next_trains"][0]["transfer_stations"], ["A12"])

    def test_stale_or_unavailable_data_does_not_guess(self):
        stale = self.query([], "2099-01-01T10:00:00+08:00",
                           fetched="2099-01-01T09:30:00+08:00")
        self.assertEqual(stale["status"], "stale_data")
        missing = self.query(None)
        self.assertEqual(missing["status"], "unavailable")
        self.assertEqual(missing["next_trains"], [])

    def test_all_cancelled_reports_suspension_without_time(self):
        cancelled = leg("X", "A8", "A13", "2099-01-01T10:05:00+08:00",
                        "2099-01-01T10:35:00+08:00", ["A8", "A13"],
                        status="cancelled")
        result = self.query([{"legs": [cancelled]}])
        self.assertEqual(result["status"], "no_service")
        self.assertEqual(result["service_status"], "suspended")
        self.assertEqual(result["next_trains"], [])


if __name__ == "__main__":
    unittest.main()
