"""Build reproducible conversational SFT data against the offline tool API."""

import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.prepare_data import QA_SOURCE_DIR, build_records, split_records, write_jsonl
from src.bot_tools import SYSTEM_PROMPT, TOOL_SCHEMA, dispatch_tool, render_answer


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/training"
CONVERTED_TIMES = {
    "001": "2026-09-21T10:00:00+08:00", "002": "2026-09-22T14:00:00+08:00",
    "003": "2026-09-23T09:00:00+08:00", "004": "2026-09-24T23:58:00+08:00",
    "042": "2026-09-25T08:00:00+08:00",
}
# Align the reviewed conversations with the capabilities actually available.
# Originals remain unchanged for audit; no external fare/routing tool exists.
CAPABILITY_REPLACEMENTS = {
    "005": [("我先查單程票票價；", "需要另查官方單程票票價；")],
    "011": [("確認航廈後，我會依 A18、目的站與臺灣時間查最近及下一班，並標明預定或即時資料和查詢時間。",
             "請一併提供查詢日期與臺灣時間；確認後才能查 A18 到目的站的最近兩班預定班次，目前沒有即時資料。")],
    "018": [("你打算哪一天、幾點出發？我可以再確認當日規定。", "當日是否另有調整，請向站務人員確認。")],
    "031": [("我會查現在從 A22 出發、實際可到 A1 的最近班次及終點；如果今晚已沒有可到 A1 的車，就直接告訴你，不能把往機場的車當成往台北的車。",
             "請提供查詢日期與臺灣時間，才能查 A22 到 A1 的預定班次；這份班表不能確認即時運行。")],
    "034": [("我會查最近可到 A1 的車和末班車。", "請提供查詢日期與臺灣時間，才能查不需換車到 A1 的班次。")],
    "036": [("我會查當下兩條路的班次，再依你的高鐵發車時間比較。",
             "目前沒有高鐵班次、機捷抵達時間或轉乘銜接資料，無法比較當下哪條路較快。")],
    "041": [("我會查現在各班的終點、轉乘等待時間及抵達 A21 的時間，再告訴你哪種搭法較快；",
             "目前可查不需換車到 A21 的預定班次，但沒有抵達時間或轉乘銜接資料，無法比較哪種搭法最快；")],
    "044": [("我會查 A6 最近一班往 A1 的普通車時間。", "請提供查詢日期與臺灣時間，才能查最近一班。")],
    "051": [("若你有指定館別，我可以再查步行路線。", "請依指定館別的現場指標前往，或向站務人員確認步行路線。")],
}


def system_message(at=None):
    return {"role": "system", "content": SYSTEM_PROMPT + (
        f"\n目前臺灣時間：{at}" if at else "\n目前未提供系統時間。")}


def exchange(origin, destination, at, root, fixture=None):
    arguments = {"起站": origin, "目的站": destination, "查詢時間": at}
    kwargs = {"cache_path": root / "data/timetable/cache.json",
              "rules_path": root / "data/timetable/service_rules.json"}
    # Failure examples exercise the actual fallback, never invent train times.
    with TemporaryDirectory() as temp:
        if fixture:
            field = {"missing_cache": "cache_path", "missing_rules": "rules_path"}[fixture]
            kwargs[field] = Path(temp) / "missing.json"
        result = dispatch_tool("get_next_trains", arguments, **kwargs)
    return [
        {"role": "assistant", "tool_calls": [{"type": "function", "function": {
            "name": "get_next_trains", "arguments": arguments}}]},
        {"role": "tool", "name": "get_next_trains",
         "content": json.dumps(result, ensure_ascii=False, separators=(",", ":"))},
        {"role": "assistant", "content": render_answer(result)},
    ]


def build_training(root=ROOT):
    root = Path(root)
    originals = build_records(root)
    _, _, old_split = split_records(originals)
    rows, partitions = [], {}
    for original in originals:
        row = copy.deepcopy(original)
        identifier = row["id"]
        row["tools"] = [copy.deepcopy(TOOL_SCHEMA)]
        for before, after in CAPABILITY_REPLACEMENTS.get(identifier, []):
            for message in row["messages"]:
                if message.get("role") == "assistant" and "content" in message:
                    message["content"] = message["content"].replace(before, after)
        at = CONVERTED_TIMES.get(identifier)
        provenance = {"kind": "reviewed_markdown", "source_id": identifier,
                      "current_policy_recheck_required": True}
        if at:
            index = next(i for i, msg in enumerate(row["messages"]) if "tool_calls" in msg)
            args = row["messages"][index]["tool_calls"][0]["function"]["arguments"]
            row["messages"] = row["messages"][:index] + exchange(
                args["起站"], args["目的站"], at, root)
            prefix = {
                "002": "直達車不停 A9。", "003": "直達車不停 A22；目前無法比較轉乘後的抵達時間。",
                "042": "請搭往機場、台北方向的車。",
            }.get(identifier, "")
            row["messages"][-1]["content"] = prefix + row["messages"][-1]["content"]
            provenance = {"kind": "reviewed_normal_cache_tool", "source_id": identifier}
        if identifier == "012":
            row["messages"][-1]["content"] = (
                "直達車不停 A10 山鼻站，可從 A3 搭普通車不換車抵達。"
                "目前工具只能查不需換車的發車班次，缺少抵達與轉乘銜接資料，無法比較哪個方案最快。")
        row["messages"].insert(0, system_message(at))
        row["provenance"] = provenance
        rows.append(row)
        partitions[identifier] = "val" if identifier in old_split["val_ids"] else "train"
    cases = json.loads((root / "data/training_cases.json").read_text(encoding="utf-8"))
    for case in cases:
        at = case.get("at")
        messages = [system_message(at), {"role": "user", "content": case["question"]}]
        if "origin" in case:
            messages += exchange(case["origin"], case["destination"], at, root, case.get("fixture"))
            kind = "failure_fixture" if case.get("fixture") else "reviewed_normal_cache_tool"
        else:
            messages.append({"role": "assistant", "content": case["answer"]})
            kind = "authored_behavior"
        rows.append({"id": case["id"], "scenario_group": case["group"],
                     "messages": messages, "tools": [copy.deepcopy(TOOL_SCHEMA)],
                     "provenance": {"kind": kind, "fixture": case.get("fixture")}})
        partitions[case["id"]] = case["split"]
    train = [row for row in rows if partitions[row["id"]] == "train"]
    val = [row for row in rows if partitions[row["id"]] == "val"]
    sources = [*sorted((root / QA_SOURCE_DIR).glob("airport_mrt_qa_*.md")),
               root / "data/training_cases.json", root / "data/timetable/cache.json",
               root / "data/timetable/service_rules.json", root / "data/timetable/calendar_2026.json",
               root / "data/timetable/sources/dgpa_2026_rules.json",
               root / "data/timetable/sources/time_2026-09-21.json",
               root / "scripts/build_normal_timetable.py", root / "src/service_calendar.py",
               root / "data/station_aliases.json",
               root / "src/bot_tools.py",
               root / "src/timetable.py", root / "src/station_routes.py",
               root / "scripts/prepare_training.py", root / "scripts/prepare_data.py"]
    manifest = {
        "schema_version": 1, "purpose": "small_scale_behavior_sft_trial", "seed": 42,
        "split_method": "fixed_scenario_groups", "train_ids": [r["id"] for r in train],
        "val_ids": [r["id"] for r in val],
        "source_sha256": {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sources},
        "provenance_counts": dict(Counter(row["provenance"]["kind"] for row in rows)),
        "holdout": "data/eval/unseen_cases.jsonl is excluded from preparation and training",
    }
    return rows, train, val, manifest


def main():
    from scripts.validate_training import validate_bundle

    rows, train, val, manifest = build_training()
    for filename, records in (("all.jsonl", rows), ("train.jsonl", train), ("val.jsonl", val)):
        write_jsonl(OUTPUT / filename, records)
    manifest["file_sha256"] = {
        filename: hashlib.sha256((OUTPUT / filename).read_bytes()).hexdigest()
        for filename in ("all.jsonl", "train.jsonl", "val.jsonl")}
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    errors = validate_bundle(ROOT)
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"SFT bundle: {len(rows)} total, {len(train)} train, {len(val)} validation")


if __name__ == "__main__":
    main()
