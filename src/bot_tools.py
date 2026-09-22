"""Compact, offline tool contract shared by training and the application."""

import json
from datetime import datetime

from src.station_routes import DEFAULT_RULES, StationClarificationRequired
from src.timetable import DEFAULT_CACHE, query_direct_trains


TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_next_trains",
        "description": "查可不換車到目的站且距發車超過3分鐘的最近兩班；3分鐘內僅提醒勿趕車。可接受機捷站名暱稱；無即時、抵達或轉乘時間。",
        "parameters": {
            "type": "object",
            "properties": {
                "起站": {"type": "string", "description": "機捷站代碼、站名或已確認暱稱"},
                "目的站": {"type": "string", "description": "機捷站代碼、站名或已確認暱稱"},
                "查詢時間": {"type": "string", "description": "含時區的 ISO 8601 時間"},
            },
            "required": ["起站", "目的站", "查詢時間"],
            "additionalProperties": False,
        },
    },
}

SYSTEM_PROMPT = (
    "你是機場捷運助理，使用繁體中文。班次必須查工具，依結果回答；"
    "缺起訖站、航廈或查詢時間就追問。現在時間由系統提供，不自行猜日期。"
    "預定班表不能證明即時運行正常。不要捏造票價、抵達時間、轉乘或未取得的資料。"
    "3分鐘內發車不建議趕搭，依工具提供的較晚班次回答；不能保證一定搭得上。"
    "可把旅客提供的站名或暱稱交給工具辨識，不猜造站碼；工具要求釐清時依問題追問。"
)


def get_next_trains(origin, destination, query_time, *, cache_path=DEFAULT_CACHE,
                    rules_path=DEFAULT_RULES):
    result = {
        "status": "unavailable", "origin": origin, "destination": destination,
        "query_time": query_time, "source_type": "scheduled",
        "service_status": "unknown", "direct_only": True,
        "arrival_time_available": False, "next_trains": [],
    }
    try:
        at = datetime.fromisoformat(query_time)
        if at.tzinfo is None:
            raise ValueError("missing timezone")
    except (ValueError, TypeError):
        result["status"] = "invalid_query_time"
        return result
    try:
        raw = query_direct_trains(origin, destination, query_time,
                                  cache_path=cache_path, rules_path=rules_path)
    except StationClarificationRequired as exc:
        result.update(status="station_needs_clarification", clarification=exc.question,
                      station_candidates=exc.candidates)
        return result
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("無法辨識車站"):
            result["status"] = "invalid_station"
        return result
    result.update(status=raw["status"], origin=raw["station_id"],
                  destination=raw["destination_id"], query_time=raw["query_time"])
    for field in ("service_date", "fetched_at", "remaining_departures", "day_type",
                  "schedule_policy", "special_events_included"):
        if field in raw:
            result[field] = raw[field]
    if "boarding_buffer_minutes" in raw:
        result.update(boarding_buffer_minutes=raw["boarding_buffer_minutes"],
                      imminent_departures=[r["departure"] for r in raw["imminent_departures"]],
                      boarding_guaranteed=False)
    result["next_trains"] = [
        {"departure": item["departure"], "train_type": item["train_type"],
         "terminal": item["terminal_station_id"]}
        for item in raw["next_departures"]
    ]
    return result


def dispatch_tool(name, arguments, **kwargs):
    if name != "get_next_trains":
        raise ValueError("unsupported tool")
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    if not isinstance(arguments, dict) or set(arguments) != {"起站", "目的站", "查詢時間"}:
        raise ValueError("tool requires 起站、目的站、查詢時間")
    if not all(isinstance(value, str) and value.strip() for value in arguments.values()):
        raise ValueError("tool arguments must be nonempty strings")
    return get_next_trains(arguments["起站"], arguments["目的站"], arguments["查詢時間"], **kwargs)


def render_answer(result):
    """Grounded reference answer; no extra model inference is needed."""
    status = result["status"]
    if status == "station_needs_clarification":
        return result["clarification"]
    if status == "only_imminent_departures_remaining":
        return ("只剩3分鐘內即將發車的符合條件班次，時間過近，不建議趕車或奔跑。"
                "本營運日已無更晚的不換車班次，請洽站務人員確認其他方式。")
    if status == "ok":
        trains = "；".join(
            f"{datetime.fromisoformat(item['departure']).strftime('%m/%d %H:%M')} {item['train_type']}"
            for item in result["next_trains"])
        basis = "一般預定班表（未納入特殊活動）" if result.get("special_events_included") is False else "預定班表"
        answer = (f"依{basis}，{result['origin']} 到 {result['destination']} 可不換車搭乘："
                  f"{trains}（臺灣時間）。")
        if result.get("remaining_departures") == 1:
            answer += "這是此營運日最後一班符合條件的班次。"
        if result.get("imminent_departures"):
            answer += "另有3分鐘內即將發車的班次，建議考慮改搭上述較晚班次，避免趕車或奔跑。"
        return answer + "目前沒有抵達時間資料；實際運行請以現場看板為準，請預留進站時間。"
    if status == "no_direct_departures_remaining":
        return (f"依 {result['service_date']} 預定班表，{result['origin']} 到 {result['destination']} "
                "已無後續不需換車的班次。尚未計算轉乘方案，不能據此判定全線停駛；請洽站務人員確認替代交通。")
    if status == "date_not_cached":
        return f"本機沒有 {result['service_date']} 的這份班表，無法提供班次。請先更新指定日期的資料。"
    return {
        "outside_publication_horizon": "日期超出這份班表的官方公布範圍，請更新資料後再查詢。",
        "service_rules_unavailable": "車種停靠規則尚待核對，目前無法確認能到目的站的最近班次。請洽站務人員。",
        "same_station": f"起站與目的站都是 {result['origin']}，不需要搭車。",
        "invalid_station": "無法辨識起站或目的站，請提供機捷站代碼或完整站名。",
        "invalid_query_time": "請提供查詢日期、時間與時區，才能查詢對應班次。",
        "unavailable": "本機班表暫時無法讀取，目前不能確認班次；請核對月台看板或洽站務人員。",
    }[status]
