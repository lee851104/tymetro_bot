"""Validate the exact SFT partitions, source hashes, and tool conversations."""

import hashlib
import json
from pathlib import Path

from scripts.validate_data import load_jsonl
from src.bot_tools import TOOL_SCHEMA


ROOT = Path(__file__).resolve().parents[1]


def validate_bundle(root=ROOT, data_dir=None):
    root = Path(root)
    data_dir = Path(data_dir) if data_dir else root / "data/training"
    try:
        all_rows, train, val = [load_jsonl(data_dir / name) for name in
                                ("all.jsonl", "train.jsonl", "val.jsonl")]
        manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [str(exc)]
    errors = []
    canonical = {r["id"]: r for r in all_rows}
    if not all_rows or len(canonical) != len(all_rows):
        errors.append("missing records or duplicate IDs")
    for name, rows in (("train", train), ("val", val)):
        ids = [r["id"] for r in rows]
        if not rows or len(set(ids)) != len(ids) or manifest.get(name + "_ids") != ids:
            errors.append(f"{name}: empty, duplicate, or manifest ID mismatch")
        for row in rows:
            if row != canonical.get(row["id"]):
                errors.append(f"{name}/{row['id']}: content differs from all.jsonl")
    if ({r["id"] for r in train} & {r["id"] for r in val}
            or len(train) + len(val) != len(all_rows)
            or {r["id"] for r in train + val} != set(canonical)):
        errors.append("split IDs overlap or records are missing")
    if {r["scenario_group"] for r in train} & {r["scenario_group"] for r in val}:
        errors.append("scenario group leakage")
    train_content = {json.dumps(r["messages"], ensure_ascii=False, sort_keys=True) for r in train}
    val_content = {json.dumps(r["messages"], ensure_ascii=False, sort_keys=True) for r in val}
    if train_content & val_content:
        errors.append("identical conversation leakage across train and validation")
    for mapping, base in (("source_sha256", root), ("file_sha256", data_dir)):
        if not manifest.get(mapping):
            errors.append(f"missing {mapping}")
        for name, expected in manifest.get(mapping, {}).items():
            path = (base / name).resolve()
            if not path.is_relative_to(base.resolve()):
                errors.append(f"invalid manifest path: {name}")
                continue
            if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                errors.append(f"changed input/output: {name}; rebuild training bundle")
    for row in all_rows:
        label = row["id"]
        messages = row.get("messages", [])
        if row.get("tools") != [TOOL_SCHEMA]:
            errors.append(f"{label}: unexpected tool schema")
        if (len(messages) < 3 or messages[0].get("role") != "system"
                or messages[1].get("role") != "user"
                or messages[-1].get("role") != "assistant"
                or not messages[-1].get("content")):
            errors.append(f"{label}: invalid conversation boundaries")
            continue
        waiting = None
        previous = "system"
        for message in messages[1:]:
            role = message.get("role")
            allowed = {"system": {"user"}, "user": {"assistant"},
                       "assistant": {"user", "tool"}, "tool": {"assistant"}}
            if role not in allowed.get(previous, set()):
                errors.append(f"{label}: invalid role order")
            if waiting is not None and role != "tool":
                errors.append(f"{label}: unanswered tool call")
            if message.get("tool_calls"):
                calls = message["tool_calls"]
                if role != "assistant" or len(calls) != 1:
                    errors.append(f"{label}: invalid tool calls")
                    continue
                function = calls[0].get("function", {})
                args = function.get("arguments", {})
                if (function.get("name") != "get_next_trains"
                        or set(args) != {"起站", "目的站", "查詢時間"}
                        or not all(isinstance(v, str) and v for v in args.values())):
                    errors.append(f"{label}: invalid tool arguments")
                if args.get("查詢時間", "not supplied") not in messages[0]["content"]:
                    errors.append(f"{label}: query time lacks runtime context")
                waiting = args
            elif role == "tool":
                if waiting is None or message.get("name") != "get_next_trains":
                    errors.append(f"{label}: unexpected tool result")
                try:
                    output = json.loads(message["content"])
                    if output.get("query_time") != (waiting or {}).get("查詢時間"):
                        errors.append(f"{label}: query/result time mismatch")
                    if (output.get("service_status") != "unknown"
                            or output.get("source_type") != "scheduled"
                            or output.get("arrival_time_available") is not False
                            or output.get("direct_only") is not True):
                        errors.append(f"{label}: fabricated capabilities")
                    trains = output["next_trains"]
                    if (not isinstance(trains, list) or len(trains) > 2
                            or bool(trains) != (output.get("status") == "ok")):
                        errors.append(f"{label}: train list/status mismatch")
                except (ValueError, KeyError, TypeError):
                    errors.append(f"{label}: invalid tool JSON")
                waiting = None
            previous = role
        if waiting is not None:
            errors.append(f"{label}: unanswered tool call")
        if "{{" in json.dumps(row, ensure_ascii=False) or "2099-" in json.dumps(row):
            errors.append(f"{label}: unresolved placeholder or legacy mock data")
    return errors


def main():
    errors = validate_bundle()
    if errors:
        raise SystemExit("\n".join(errors))
    print("SFT data, exact partitions, sources, and tool conversations validated")


if __name__ == "__main__":
    main()
