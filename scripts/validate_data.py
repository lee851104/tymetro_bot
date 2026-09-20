"""Validate reviewed-question conversion before any GPU training."""

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_IDS = ({f"{number:03d}" for number in range(1, 47)}
                | {"048", "049", "051", "052", "053", "054"}) - {
                    "013", "017", "047", "050"}
PLACEHOLDER = re.compile(r"\{\{.*?\}\}")
FORBIDDEN = ("**來源", "站務審核", "站務補充", "修訂狀態", "http://", "https://")


def validate_records(records):
    errors = []
    ids = [record.get("id") for record in records]
    if len(records) != 50:
        errors.append(f"expected 50 records, got {len(records)}")
    if len(ids) != len(set(ids)):
        errors.append("duplicate question IDs")
    if set(ids) != EXPECTED_IDS:
        errors.append(f"missing={sorted(EXPECTED_IDS - set(ids))}; "
                      f"extra={sorted(set(ids) - EXPECTED_IDS)}")

    for record in records:
        identifier = record.get("id", "unknown")
        if set(record) != {"id", "scenario_group", "messages", "tools"}:
            errors.append(f"{identifier}: unexpected columns")
        messages = record.get("messages", [])
        if not messages or messages[0].get("role") != "user":
            errors.append(f"{identifier}: must begin with a user message")
            continue
        if messages[-1].get("role") != "assistant" or not messages[-1].get("content"):
            errors.append(f"{identifier}: must end with an assistant answer")
        if not any(message.get("role") == "user" for message in messages):
            errors.append(f"{identifier}: missing passenger question")
        if not any(message.get("role") == "assistant" and message.get("content")
                   for message in messages):
            errors.append(f"{identifier}: missing robot answer")
        if not record.get("tools"):
            errors.append(f"{identifier}: missing tool schema")

        waiting_for_tool = False
        for index, message in enumerate(messages):
            role = message.get("role")
            if role not in {"user", "assistant", "tool"}:
                errors.append(f"{identifier}: invalid role at {index}")
            if role == "user" and index and messages[index - 1]["role"] != "assistant":
                errors.append(f"{identifier}: invalid user order at {index}")
            if role == "assistant" and "tool_calls" in message:
                if not message["tool_calls"]:
                    errors.append(f"{identifier}: empty tool call")
                waiting_for_tool = True
            elif role == "tool":
                if not waiting_for_tool:
                    errors.append(f"{identifier}: unexpected tool response")
                waiting_for_tool = False
                try:
                    output = json.loads(message["content"])
                except (ValueError, KeyError, TypeError):
                    errors.append(f"{identifier}: tool output is not JSON")
                    continue
                if output.get("source_type") not in {"scheduled", "realtime"}:
                    errors.append(f"{identifier}: missing source type")
                if not output.get("fetched_at") or not output.get("query_time"):
                    errors.append(f"{identifier}: missing tool data/query time")
                if output.get("status") not in {"ok", "no_service", "stale_data",
                                                "unavailable"}:
                    errors.append(f"{identifier}: invalid tool status")
                if output.get("service_status") not in {
                        "normal", "delayed", "suspended", "partial_disruption",
                        "unknown"}:
                    errors.append(f"{identifier}: missing service status")
                trains = output.get("next_trains", [])
                if not isinstance(trains, list) or len(trains) > 2:
                    errors.append(f"{identifier}: invalid next trains")
                else:
                    for train in trains:
                        if (not train.get("departure") or not train.get("arrival")
                                or "transfer_stations" not in train
                                or "transfer_wait_minutes" not in train):
                            errors.append(f"{identifier}: incomplete journey")
                        for leg in train.get("legs", []):
                            if not leg.get("direction"):
                                errors.append(f"{identifier}: missing direction")
            elif role == "assistant" and index and messages[index - 1]["role"] == "assistant":
                errors.append(f"{identifier}: consecutive assistant messages")
        if waiting_for_tool:
            errors.append(f"{identifier}: unanswered tool call")
        raw = json.dumps(record, ensure_ascii=False)
        if PLACEHOLDER.search(raw):
            errors.append(f"{identifier}: unresolved placeholder")
        if any(fragment in raw for fragment in FORBIDDEN):
            errors.append(f"{identifier}: review/source text leaked into training")
    return errors


def load_jsonl(path):
    records = []
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
    return records


def validate_outputs(root=ROOT):
    root = Path(root)
    try:
        all_records = load_jsonl(root / "data" / "processed" / "all.jsonl")
        train = load_jsonl(root / "data" / "processed" / "train.jsonl")
        val = load_jsonl(root / "data" / "processed" / "val.jsonl")
        manifest = json.loads((root / "data" / "split_manifest.json").read_text(
            encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [str(exc)]
    errors = validate_records(all_records)
    all_ids = {record["id"] for record in all_records}
    train_ids = {record["id"] for record in train}
    val_ids = {record["id"] for record in val}
    if (len(train), len(val)) != (40, 10):
        errors.append("written split is not 40/10")
    if train_ids & val_ids or train_ids | val_ids != all_ids:
        errors.append("written split has leakage or missing IDs")
    if {record["scenario_group"] for record in train} & {
            record["scenario_group"] for record in val}:
        errors.append("written split has scenario group leakage")
    if set(manifest.get("train_ids", [])) != train_ids:
        errors.append("manifest train IDs do not match JSONL")
    if set(manifest.get("val_ids", [])) != val_ids:
        errors.append("manifest validation IDs do not match JSONL")
    if manifest.get("seed") != 42:
        errors.append("manifest seed must be 42")
    return errors


def main():
    errors = validate_outputs(ROOT)
    if errors:
        raise SystemExit("\n".join(errors))
    print("50 records and 40/10 split passed structural validation")


if __name__ == "__main__":
    main()
