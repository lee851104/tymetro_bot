"""Compare base/adapter behavior on a small, fixed validation probe.

Outputs transcripts and exact tool-call matching, not a production accuracy
score. The 20 final holdout questions remain untouched.
"""

import argparse
import json
from pathlib import Path

from scripts.train_lora import MODEL_ID, ROOT, dataset_digest
from scripts.validate_data import load_jsonl
from src.model_inference import (CONTEXT_LENGTH, GENERATION_CONFIG, calls_equivalent,
                                 load_generator, parse_call, run_turn)


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--base", action="store_true")
    mode.add_argument("--adapter", type=Path)
    parser.add_argument("--ids", nargs="+", default=["002", "003", "004", "V001", "V004"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = [r for r in load_jsonl(ROOT / "data/training/val.jsonl") if r["id"] in args.ids]
    if len(rows) != len(set(args.ids)):
        raise SystemExit("IDs must be in the validation partition")
    generate, model_evidence = load_generator(args.adapter)

    records = []
    for row in rows:
        first = next(i for i, m in enumerate(row["messages"]) if m["role"] == "assistant")
        messages = row["messages"][:first]
        expected = row["messages"][first].get("tool_calls", [])
        expected = expected[0]["function"] if expected else None
        record = {"id": row["id"], "prompt": messages, "expected_call": expected,
                  "reference_answer": row["messages"][-1]["content"],
                  **run_turn(generate, messages, row["tools"])}
        record["call_matches"] = not record.get("tool_error") and record["actual_call"] == expected
        record["call_equivalent"] = not record.get("tool_error") and calls_equivalent(record["actual_call"], expected)
        records.append(record)
        print(f"{row['id']}: exact={record['call_matches']}, equivalent={record['call_equivalent']}", flush=True)
    report = {"model": str(args.adapter) if args.adapter else MODEL_ID,
              "dataset_sha256": dataset_digest(), "generation": {
                  **GENERATION_CONFIG, "context_length": CONTEXT_LENGTH},
              "model_evidence": model_evidence,
              "matched": sum(r["call_matches"] for r in records), "count": len(records),
              "equivalent": sum(r["call_equivalent"] for r in records),
              "scope": "validation probe; answer quality requires manual review", "records": records}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
