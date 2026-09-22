"""Reproducible data inspection before training; never reads final holdout cases."""

import argparse
import hashlib
import json
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path

from scripts.train_lora import dataset_digest
from scripts.validate_data import load_jsonl
from scripts.validate_training import ROOT, validate_bundle
from src.timetable import TAIPEI


def summarize(rows):
    conversations = [json.dumps(row["messages"], ensure_ascii=False, sort_keys=True) for row in rows]
    tool_rows = [row for row in rows if any(m.get("tool_calls") for m in row["messages"])]
    answers = [m["content"] for row in rows for m in row["messages"]
               if m["role"] == "assistant" and m.get("content")]
    statuses = Counter(json.loads(m["content"])["status"] for row in rows
                       for m in row["messages"] if m["role"] == "tool")
    lengths = [len(answer) for answer in answers]
    return {
        "records": len(rows), "scenario_groups": len({r["scenario_group"] for r in rows}),
        "with_tool_calls": len(tool_rows), "without_tool_calls": len(rows) - len(tool_rows),
        "tool_conversation_percent": round(100 * len(tool_rows) / len(rows), 2),
        "tool_result_status_counts": dict(sorted(statuses.items())),
        "scenario_group_counts": dict(sorted(Counter(r["scenario_group"] for r in rows).items())),
        "exact_duplicate_conversations": len(rows) - len(set(conversations)),
        "empty_text_messages": sum(not m.get("content", "").strip() and not m.get("tool_calls")
                                   for row in rows for m in row["messages"]),
        "assistant_text_characters": {"count": len(lengths), "minimum": min(lengths),
                                      "median": statistics.median(lengths), "maximum": max(lengths)},
    }


def build_profile(data_dir):
    errors = validate_bundle(ROOT, data_dir)
    if errors:
        raise ValueError("data validation failed: " + "; ".join(errors))
    train, val = [load_jsonl(data_dir / f"{name}.jsonl") for name in ("train", "val")]
    prompt_set = lambda rows: {json.dumps(r["messages"], ensure_ascii=False, sort_keys=True) for r in rows}
    return {
        "schema_version": 1, "generated_at": datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "data_directory": str(data_dir), "dataset_sha256": dataset_digest(ROOT, data_dir),
        "file_sha256": {name: hashlib.sha256((data_dir / name).read_bytes()).hexdigest()
                        for name in ("train.jsonl", "val.jsonl", "manifest.json")},
        "partitions": {"train": summarize(train), "validation": summarize(val)},
        "cross_partition_overlap": {
            "ids": sorted({r["id"] for r in train} & {r["id"] for r in val}),
            "scenario_groups": sorted({r["scenario_group"] for r in train} &
                                      {r["scenario_group"] for r in val}),
            "exact_conversations": len(prompt_set(train) & prompt_set(val)),
        },
        "final_holdout_read": False,
        "limitations": ["Exact comparisons do not prove absence of semantic near-duplicates.",
                        "Dataset mix is descriptive; its effect on model quality needs a controlled experiment.",
                        "Factual correctness and current applicability of service rules need source review."],
        "cleaning_policy": "No mutation; preserve Traditional Chinese, numbers, station codes, times and punctuation.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/training")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/training_data_profile.json")
    args = parser.parse_args()
    profile = build_profile(args.data_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name, part in profile["partitions"].items():
        print(f"{name}: {part['records']} records; tool conversations "
              f"{part['with_tool_calls']} ({part['tool_conversation_percent']}%); "
              f"duplicates {part['exact_duplicate_conversations']}; empty {part['empty_text_messages']}")
    print("Cross-partition overlap:", profile["cross_partition_overlap"])
    print("Profile saved to", args.output)


if __name__ == "__main__":
    main()
