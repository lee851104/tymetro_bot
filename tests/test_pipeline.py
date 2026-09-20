import json
import copy
import unittest
from pathlib import Path

from scripts.prepare_data import build_records, split_records
from scripts.validate_data import validate_outputs, validate_records


ROOT = Path(__file__).resolve().parents[1]


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = build_records(ROOT)

    def test_all_reviewed_questions_become_one_record_each(self):
        ids = [record["id"] for record in self.records]
        self.assertEqual(len(ids), 50)
        self.assertEqual(len(set(ids)), 50)
        self.assertNotIn("013", ids)
        self.assertNotIn("017", ids)
        self.assertNotIn("047", ids)
        self.assertNotIn("050", ids)

    def test_multiturn_question_stays_together(self):
        record = next(item for item in self.records if item["id"] == "001")
        self.assertEqual(record["messages"][0]["role"], "user")
        self.assertEqual(record["messages"][2]["role"], "user")
        self.assertTrue(any(message["role"] == "tool" for message in record["messages"]))

    def test_placeholder_and_review_text_are_absent(self):
        self.assertEqual(validate_records(self.records), [])
        raw = json.dumps(self.records, ensure_ascii=False)
        self.assertNotIn("{{", raw)
        self.assertNotIn("站務審核", raw)
        self.assertNotIn("修訂狀態", raw)
        self.assertNotIn("**來源", raw)

    def test_split_is_40_10_without_group_leakage(self):
        train, val, manifest = split_records(self.records)
        self.assertEqual((len(train), len(val)), (40, 10))
        self.assertEqual({r["id"] for r in train} & {r["id"] for r in val}, set())
        self.assertEqual(set(manifest["train_ids"]) | set(manifest["val_ids"]),
                         {r["id"] for r in self.records})
        train_groups = {r["scenario_group"] for r in train}
        val_groups = {r["scenario_group"] for r in val}
        self.assertFalse(train_groups & val_groups)

    def test_unseen_cases_are_separate_and_new(self):
        path = ROOT / "data" / "eval" / "unseen_cases.jsonl"
        cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertGreaterEqual(len(cases), 20)
        self.assertEqual(len({case["id"] for case in cases}), len(cases))
        reviewed_questions = {message["content"] for record in self.records
                              for message in record["messages"] if message["role"] == "user"}
        for case in cases:
            self.assertNotIn(case["user"], reviewed_questions)
            self.assertTrue(case["expected_behavior"])

    def test_written_jsonl_and_manifest_validate_together(self):
        self.assertEqual(validate_outputs(ROOT), [])

    def test_tool_contract_rejects_missing_status_and_direction(self):
        records = copy.deepcopy(self.records)
        record = next(item for item in records if item["id"] == "001")
        tool_message = next(message for message in record["messages"]
                            if message["role"] == "tool")
        output = json.loads(tool_message["content"])
        del output["service_status"]
        del output["next_trains"][0]["legs"][0]["direction"]
        tool_message["content"] = json.dumps(output, ensure_ascii=False)
        errors = validate_records(records)
        self.assertTrue(any("service status" in error for error in errors))
        self.assertTrue(any("direction" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
