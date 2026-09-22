import json
import unittest

from src.bot_tools import TOOL_SCHEMA
from src.model_inference import calls_equivalent, decode_completion, run_turn


class ModelInferenceTests(unittest.TestCase):
    def test_decode_removes_prompt_by_token_position(self):
        class Tokenizer:
            def decode(self, ids, **kwargs):
                return " ".join(str(token) for token in ids)
        self.assertEqual(decode_completion(Tokenizer(), [100, 200, 300, 400], 2), "300 400")

    def test_shared_turn_executes_tool_and_retains_final_answer(self):
        call = {"name": "get_next_trains", "arguments": {
            "起站": "北車", "目的站": "二航", "查詢時間": "2026-09-21T10:00:00+08:00"}}
        seen = []
        def generate(messages, tools):
            seen.append(messages)
            return "<tool_call>" + json.dumps(call) + "</tool_call>" if len(seen) == 1 else "請考慮較晚班次。"
        messages = [{"role": "user", "content": "查班"}]
        result = run_turn(generate, messages, [TOOL_SCHEMA])
        self.assertNotIn("tool_error", result)
        self.assertEqual(result["tool_result"]["next_trains"][0]["departure"][11:16], "10:08")
        self.assertEqual(result["final_output"], "請考慮較晚班次。")
        self.assertEqual(len(messages), 1)
        self.assertEqual(seen[1][-1]["role"], "tool")

    def test_invalid_or_repeated_tool_call_is_an_error(self):
        for output in ['<tool_call>', '<tool_call>{"name":"shell","arguments":{}}</tool_call>']:
            result = run_turn(lambda *args: output, [], [TOOL_SCHEMA])
            self.assertIn("tool_error", result)
        call = '<tool_call>{"name":"get_next_trains","arguments":{"起站":"A1","目的站":"A13","查詢時間":"2026-09-21T10:00:00+08:00"}}</tool_call>'
        result = run_turn(lambda *args: call, [], [TOOL_SCHEMA])
        self.assertIn("repeated", result["tool_error"])

    def test_alias_equivalence_does_not_hide_wrong_destination(self):
        expected = {"name": "get_next_trains", "arguments": {
            "起站": "A1", "目的站": "A13", "查詢時間": "2026-09-21T10:00:00+08:00"}}
        actual = {"name": "get_next_trains", "arguments": {**expected["arguments"], "起站": "北車", "目的站": "二航"}}
        self.assertTrue(calls_equivalent(actual, expected))
        actual["arguments"]["目的站"] = "一航"
        self.assertFalse(calls_equivalent(actual, expected))


if __name__ == "__main__":
    unittest.main()
