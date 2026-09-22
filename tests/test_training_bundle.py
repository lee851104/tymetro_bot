import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_training import ROOT, build_training
from scripts.evaluate_adapter import parse_call
from scripts.validate_training import validate_bundle
from src.bot_tools import dispatch_tool, get_next_trains, render_answer


class TrainingBundleTests(unittest.TestCase):
    def test_probe_rejects_partial_multiple_and_non_object_tool_calls(self):
        valid = '<tool_call>{"name":"get_next_trains","arguments":{}}</tool_call>'
        self.assertEqual(parse_call(valid)["name"], "get_next_trains")
        self.assertIsNone(parse_call("請問你的目的站？"))
        for output in ("<tool_call>", valid + valid, "<tool_call>null</tool_call>"):
            with self.subTest(output=output), self.assertRaises(ValueError):
                parse_call(output)

    def test_bundle_is_reproducible_and_valid(self):
        self.assertEqual(validate_bundle(), [])
        rows, train, val, manifest = build_training()
        self.assertEqual((len(rows), len(train), len(val)), (87, 70, 17))
        written = [json.loads(line) for line in (ROOT / "data/training/all.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(rows, written)
        self.assertFalse({r["scenario_group"] for r in train} & {r["scenario_group"] for r in val})

    def test_mutated_split_answer_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            for path in (ROOT / "data/training").glob("*.json*"):
                (output / path.name).write_bytes(path.read_bytes())
            path = output / "train.jsonl"
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            rows[0]["messages"][-1]["content"] = "錯誤答案"
            path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
            errors = validate_bundle(ROOT, output)
            self.assertTrue(any("content differs" in err for err in errors))
            self.assertTrue(any("changed input/output" in err for err in errors))

    def test_tool_filters_express_and_does_not_claim_live_status(self):
        result = dispatch_tool("get_next_trains", {"起站": "A8", "目的站": "A10", "查詢時間": "2026-09-21T10:00:00+08:00"})
        self.assertEqual(result["status"], "ok")
        self.assertEqual([t["departure"][11:16] for t in result["next_trains"]], ["10:08", "10:23"])
        self.assertEqual(result["service_status"], "unknown")
        self.assertFalse(result["arrival_time_available"])

    def test_missing_corrupt_cache_and_rules_have_distinct_fallbacks(self):
        args = ("A8", "A13", "2026-09-21T10:00:00+08:00")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "cache.json"
            self.assertEqual(get_next_trains(*args, cache_path=path)["status"], "unavailable")
            path.write_text("{invalid}")
            self.assertEqual(get_next_trains(*args, cache_path=path)["status"], "unavailable")
            self.assertEqual(get_next_trains(*args, rules_path=path)["status"], "service_rules_unavailable")

    def test_uncached_date_and_last_service_do_not_imply_suspension(self):
        result = get_next_trains("A8", "A13", "2030-01-01T10:00:00+08:00")
        self.assertEqual(result["status"], "date_not_cached")
        self.assertFalse(result["next_trains"])
        result = get_next_trains("A18", "A1", "2026-09-24T23:58:00+08:00")
        self.assertEqual(result["status"], "no_direct_departures_remaining")
        self.assertIn("不能據此判定全線停駛", render_answer(result))

    def test_tool_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            dispatch_tool("get_next_trains", {"起站": "A8"})
        self.assertEqual(get_next_trains("A8", "A13", "2026-09-21T10:00:00")["status"], "invalid_query_time")
        self.assertEqual(get_next_trains("A99", "A13", "2026-09-21T10:00:00+08:00")["status"], "invalid_station")


if __name__ == "__main__":
    unittest.main()
