"""Convert the five reviewed Markdown files to conversational JSONL.

Run from the project root: ``python -m scripts.prepare_data``.
The schedule examples use dates in 2099 and synthetic data only.
"""

import json
import re
from pathlib import Path

from src.schedule import get_next_trains


ROOT = Path(__file__).resolve().parents[1]
HEADING = re.compile(r"^## (\d{3})｜")
DIALOGUE = re.compile(r"^- (旅客|機器人)：(.+)$")
EXCLUDED = {"013", "017", "047", "050"}
VALIDATION_GROUPS = {
    "small_station_to_taipei": {"002", "044"},
    "late_to_taipei": {"004", "031", "034"},
    "south_express_choice": {"003", "041"},
    "city_checkin": {"009", "029"},
    "unopened_station": {"052"},
}
GROUPS = {
    **VALIDATION_GROUPS,
    "airport_departures": {"001", "011"},
    "express_to_local": {"012", "042"},
    "fare_and_passes": {"005", "024", "025"},
    "electronic_payment": {"006", "016", "038", "045"},
    "rail_transfer": {"010", "026", "027", "036", "053"},
    "accessibility": {"008", "037", "051"},
    "trip_to_a18": {"043"},
    "ticket_refund": {"023", "046"},
    "incident_response": {"020", "030", "048"},
}
TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_next_trains",
        "description": "依起站、目的站和臺灣時間查詢可搭班次；回傳資料類型與擷取時間。",
        "parameters": {
            "type": "object",
            "properties": {
                "起站": {"type": "string", "description": "機捷站代碼，例如 A8"},
                "目的站": {"type": "string", "description": "機捷站代碼，例如 A13"},
                "查詢時間": {"type": "string", "description": "含 +08:00 時區的 ISO 8601 時間"},
            },
            "required": ["起站", "目的站", "查詢時間"],
        },
    },
}


def _leg(train_id, origin, destination, departure, arrival, train_type="普通車"):
    return {"legs": [{
        "train_id": train_id,
        "origin": origin,
        "destination": destination,
        "departure": departure,
        "arrival": arrival,
        "stops": [origin, destination],
        "train_type": train_type,
        "status": "normal",
    }]}


def _tool_exchange(origin, destination, query_time, journeys, answer):
    result = get_next_trains(origin, destination, query_time, journeys,
                             query_time, "scheduled")
    return [
        {"role": "assistant", "tool_calls": [{
            "type": "function",
            "function": {
                "name": "get_next_trains",
                "arguments": {"起站": origin, "目的站": destination,
                              "查詢時間": query_time},
            },
        }]},
        {"role": "tool", "name": "get_next_trains",
         "content": json.dumps(result, ensure_ascii=False)},
        {"role": "assistant", "content": answer},
    ]


def _replace_dynamic(identifier, messages):
    """Resolve reviewed placeholders without teaching time as static fact."""
    if identifier == "001":
        sample = [
            _leg("SIM-A", "A8", "A13", "2099-01-01T10:08:00+08:00",
                 "2099-01-01T10:42:00+08:00"),
            _leg("SIM-B", "A8", "A13", "2099-01-01T10:23:00+08:00",
                 "2099-01-01T10:57:00+08:00"),
        ]
        return messages[:3] + _tool_exchange(
            "A8", "A13", "2099-01-01T10:00:00+08:00", sample,
            "依這筆測試用預定班表，A8 往 A13 最近可搭的普通車 10:08 發車，"
            "下一班 10:23。資料查詢時間是 2099-01-01 10:00（臺灣時間）；"
            "這是模擬資料，不供實際搭乘，現場請重新查詢並核對月台看板。")
    if identifier == "002":
        sample = [
            _leg("SIM-C", "A9", "A1", "2099-01-02T14:12:00+08:00",
                 "2099-01-02T15:02:00+08:00"),
            _leg("SIM-D", "A9", "A1", "2099-01-02T14:27:00+08:00",
                 "2099-01-02T15:17:00+08:00"),
        ]
        return messages[:1] + _tool_exchange(
            "A9", "A1", "2099-01-02T14:00:00+08:00", sample,
            "一般直達車不停 A9。依這筆測試用預定班表，A9 往 A1 最近的普通車"
            "14:12 發車，下一班 14:27；查詢時間是 2099-01-02 14:00"
            "（臺灣時間）。這是模擬資料，不供實際搭乘；轉乘直達車是否更快，"
            "還要查 A8 的銜接與候車時間。")
    if identifier == "003":
        sample = [
            _leg("SIM-E", "A22", "A12", "2099-01-03T09:07:00+08:00",
                 "2099-01-03T09:47:00+08:00"),
            _leg("SIM-F", "A22", "A12", "2099-01-03T09:22:00+08:00",
                 "2099-01-03T10:02:00+08:00"),
        ]
        return messages[:1] + _tool_exchange(
            "A22", "A12", "2099-01-03T09:00:00+08:00", sample,
            "依這筆測試用預定班表，A22 往 A12 最近可搭普通車 09:07 發車，"
            "下一班 09:22；查詢時間是 2099-01-03 09:00（臺灣時間）。"
            "直達車是否較早抵達，要另查 A21 的轉乘候車時間。"
            "這是模擬資料，不供實際搭乘。")
    if identifier == "004":
        return messages[:1] + _tool_exchange(
            "A18", "A1", "2099-01-04T23:58:00+08:00", [],
            "依這筆測試用預定班表，今晚 A18 往 A1 已無可搭班次。"
            "資料查詢時間是 2099-01-04 23:58（臺灣時間）。"
            "這是模擬資料，不供實際搭乘；若有營運異動，請以站內公告為準。")
    if identifier == "005":
        messages[-1] = {"role": "assistant", "content":
                        "A8 到 A13 的單程票價會隨公告調整，我需要查當日票價才"
                        "能報金額；目前沒有票價查詢結果，不能猜測。其他票種依"
                        "各自有效規則計價。"}
    if identifier == "011":
        messages[-1] = {"role": "assistant", "content":
                        "你要到第一航廈 A12，還是第二航廈 A13？兩站要分開確認"
                        "實際停靠班次。確認航廈後，我會依 A18、目的站與臺灣"
                        "時間查最近及下一班，並標明預定或即時資料和查詢時間。"}
    if identifier == "012":
        messages[-1] = {"role": "assistant", "content":
                        "直達車不停 A10 山鼻站。你可以從 A3 搭普通車直達；"
                        "若先搭直達車到 A8 再轉普通車，須把 A8 候車時間算進去。"
                        "目前沒有當下班次資料，無法判斷哪條路較早抵達；"
                        "查到兩種方案後再比較。"}
    if identifier == "042":
        sample = [
            _leg("SIM-G", "A15", "A12", "2099-01-05T08:06:00+08:00",
                 "2099-01-05T08:24:00+08:00"),
            _leg("SIM-H", "A15", "A12", "2099-01-05T08:21:00+08:00",
                 "2099-01-05T08:39:00+08:00"),
        ]
        return messages[:1] + _tool_exchange(
            "A15", "A12", "2099-01-05T08:00:00+08:00", sample,
            "A15 往 A12 要搭往機場、台北方向的普通車，直達車不停 A15。"
            "依這筆測試用預定班表，最近一班 08:06 發車、08:24 抵達；"
            "下一班 08:21 發車。查詢時間是 2099-01-05 08:00（臺灣時間）。"
            "這是模擬資料，不供實際搭乘；請以月台看板確認。")
    return messages


def build_records(root=ROOT):
    records = []
    for path in sorted(Path(root).glob("airport_mrt_qa_*.md")):
        current_id = None
        in_dialogue = False
        messages = []

        def finish():
            if current_id and current_id not in EXCLUDED:
                group = next((name for name, members in GROUPS.items()
                              if current_id in members), f"single_{current_id}")
                records.append({"id": current_id, "scenario_group": group,
                                "messages": _replace_dynamic(current_id, messages.copy()),
                                "tools": [TOOL_SCHEMA]})

        for line in path.read_text(encoding="utf-8-sig").splitlines():
            heading = HEADING.match(line)
            if heading:
                finish()
                current_id = heading.group(1)
                messages = []
                in_dialogue = False
                continue
            if line == "**對話**":
                in_dialogue = True
                continue
            if in_dialogue and line.startswith("**"):
                in_dialogue = False
            if in_dialogue:
                turn = DIALOGUE.match(line)
                if turn:
                    messages.append({"role": "user" if turn.group(1) == "旅客"
                                     else "assistant", "content": turn.group(2).strip()})
        finish()
    return records


def split_records(records):
    validation_ids = set().union(*VALIDATION_GROUPS.values())
    train = [record for record in records if record["id"] not in validation_ids]
    val = [record for record in records if record["id"] in validation_ids]
    manifest = {"seed": 42, "method": "fixed_scenario_groups",
                "train_ids": [record["id"] for record in train],
                "val_ids": [record["id"] for record in val],
                "validation_groups": {key: sorted(value)
                                      for key, value in VALIDATION_GROUPS.items()}}
    return train, val, manifest


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def main():
    from scripts.validate_data import validate_records

    records = build_records()
    errors = validate_records(records)
    if errors:
        raise SystemExit("資料檢查未通過:\n" + "\n".join(errors))
    train, val, manifest = split_records(records)
    if len(train) != 40 or len(val) != 10:
        raise SystemExit("切分筆數不是 40/10")
    output = ROOT / "data" / "processed"
    write_jsonl(output / "all.jsonl", records)
    write_jsonl(output / "train.jsonl", train)
    write_jsonl(output / "val.jsonl", val)
    manifest_path = ROOT / "data" / "split_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    print("Converted 50 records; train=40, val=10")


if __name__ == "__main__":
    main()
