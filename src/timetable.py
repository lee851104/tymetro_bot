"""Parse official station timetables and query a date-specific offline cache.

These are scheduled departures, not live train positions or complete journeys.
Only the downloader imports network modules; querying this module is offline.
"""

import hashlib
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

from src.station_routes import (DEFAULT_RULES, ServiceRuleError, load_service_rules,
                                resolve_station, route_for_service)


TAIPEI = timezone(timedelta(hours=8))
BASE_URL = "https://www.tymetro.com.tw/tymetro-new/tw/_pages/travel-guide/"
DEFAULT_CACHE = Path(__file__).resolve().parents[1] / "data/timetable/cache.json"
OFFICIAL_CACHE = DEFAULT_CACHE.with_name("official_cache.json")
SERVICE_NAMES = {
    "des01": "直達車",
    "des02": "尖峰增停直達車",
    "des03": "普通車",
    "des04": "往機場加班普通車",
    "des05": "尖峰跳站普通車",
    "des06": "設計展調整往 A21 普通車",
    "des07": "設計展 A12–A21 區間普通車",
}


class ParseError(ValueError):
    """The downloaded page cannot safely be interpreted as a timetable."""


class Node:
    def __init__(self, tag="root", attrs=()):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []

    def find(self, tag=None, class_name=None):
        for child in self.children:
            if isinstance(child, Node):
                if ((tag is None or child.tag == tag)
                        and (class_name is None
                             or class_name in child.attrs.get("class", "").split())):
                    yield child
                yield from child.find(tag, class_name)

    def text(self):
        return "".join(child.text() if isinstance(child, Node) else child
                       for child in self.children)


class Document(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, value):
        self.stack[-1].children.append(value)


def clean(value):
    return " ".join(value.split())


def parse_timetable(html, station_id, service_date):
    """Validate station/date, both directions and duplicate display tables."""
    date.fromisoformat(service_date)
    doc = Document(html).root
    selected = [node.attrs.get("value") for node in doc.find("input")
                if node.attrs.get("id") == "timetable_date"]
    if selected != [service_date]:
        raise ParseError(f"requested {service_date}; page selected {selected}")
    stations = {}
    for link in doc.find("a"):
        match = re.fullmatch(r"timetable-(A\d+a?)", link.attrs.get("href", ""))
        if match:
            sid = match.group(1)
            label = clean(link.text())
            stations[sid] = label.removeprefix(sid).strip()
    if station_id not in stations:
        raise ParseError(f"station {station_id} missing from page")

    notices = [clean(node.text()) for node in doc.find("div")
               if node.attrs.get("style", "").replace(" ", "") == "color:red;"
               and clean(node.text()).startswith("＊")]
    expiry = re.search(r"目前時刻表更新至(\d+)/(\d+)/(\d+)", " ".join(notices))
    if not expiry:
        raise ParseError("official publication horizon missing")
    year, month, day = map(int, expiry.groups())
    published_through = date(year + 1911 if year < 1911 else year, month, day)
    if date.fromisoformat(service_date) > published_through:
        raise ParseError(f"requested date exceeds publication horizon {published_through}")

    legends = {}
    for description in doc.find(class_name="time-description"):
        for item in description.find("li"):
            for span in item.find("span"):
                for code in span.attrs.get("class", "").split():
                    if re.fullmatch(r"des\d+", code):
                        legends[code] = clean(item.text()).removeprefix("00").strip()

    directions = {}
    copies = {"up": 0, "down": 0}
    for table in doc.find("table", "time-table"):
        captions = [clean(node.text()) for node in table.find("caption")]
        if len(captions) != 1 or not re.search(
                rf"時刻表\s*:\s*{re.escape(station_id)}\s", captions[0]):
            raise ParseError(f"wrong station caption: {captions}")
        bodies = list(table.find("tbody"))
        if len(bodies) != 1:
            raise ParseError("expected one timetable body")
        direction = bodies[0].attrs.get("class")
        if direction not in copies:
            raise ParseError(f"unknown direction {direction}")
        label = table.attrs.get("summary", "").split(":", 1)[-1]
        rows, seen_hours = [], []
        notes = {}
        for row in bodies[0].find("tr"):
            headers = list(row.find("th"))
            if len(headers) != 1 or not clean(headers[0].text()).isdigit():
                raise ParseError("missing hour row")
            hour = int(clean(headers[0].text()))
            if not 0 <= hour <= 23:
                raise ParseError(f"invalid hour {hour}")
            seen_hours.append(hour)
            for cell in row.find("td"):
                for span in cell.find("span"):
                    classes = span.attrs.get("class", "").split()
                    # CSS 'downspan' also occurs in northbound tables.
                    if not {"upspan", "downspan"}.intersection(classes):
                        continue
                    codes = [code for code in classes if re.fullmatch(r"des\d+", code)]
                    if len(codes) != 1 or codes[0] not in SERVICE_NAMES or codes[0] not in legends:
                        raise ParseError(f"unknown service classification: {classes}")
                    minute_text = clean(span.text())
                    if not minute_text.isdigit() or not 0 <= int(minute_text) < 60:
                        raise ParseError(f"invalid minute {minute_text}")
                    code = codes[0]
                    rows.append({"time": f"{hour:02d}:{int(minute_text):02d}",
                                 "day_offset": int(hour < 3), "service_code": code})
                    for note in cell.find("div", "sr-only"):
                        text = clean(note.text())
                        if "-" in text:
                            notes.setdefault(code, set()).add(text)
        if seen_hours != list(range(5, 24)) + [0, 1]:
            raise ParseError(f"incomplete or changed hour table: {seen_hours}")
        rows.sort(key=lambda item: (item["day_offset"], item["time"], item["service_code"]))
        if len({(row["time"], row["day_offset"], row["service_code"]) for row in rows}) != len(rows):
            raise ParseError("duplicate departure within a direction")
        result = {"label": label, "departures": rows,
                  "source_notes": {code: sorted(values) for code, values in sorted(notes.items())}}
        # Accessible and visual tables should agree on the departures. Their
        # descriptive text may differ, so retain both for later source auditing.
        if direction in directions:
            previous = directions[direction]
            if previous["label"] != label or previous["departures"] != rows:
                raise ParseError(f"accessible/visual tables disagree: {direction}")
            for code, values in result["source_notes"].items():
                previous["source_notes"][code] = sorted(set(previous["source_notes"].get(code, [])) | set(values))
        else:
            directions[direction] = result
        copies[direction] += 1
    if copies != {"up": 2, "down": 2}:
        raise ParseError(f"expected two copies per direction, got {copies}")
    if not any(item["departures"] for item in directions.values()):
        raise ParseError("both directions empty; do not interpret as no service")
    return {"station_id": station_id, "station_name": stations[station_id],
            "service_date": service_date, "stations": stations,
            "published_through": published_through.isoformat(),
            "notices": notices, "legends": legends, "directions": directions}


def pattern_id(pattern):
    payload = json.dumps(pattern, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def add_page(cache, page, fetched_at, html_sha256):
    pattern = {"station_id": page["station_id"], "directions": page["directions"],
               "legends": page["legends"]}
    key = pattern_id(pattern)
    cache["patterns"][key] = pattern
    cache["stations"].update(page["stations"])
    cache["calendar"].setdefault(page["service_date"], {})[page["station_id"]] = {
        "pattern_id": key, "fetched_at": fetched_at,
        "source_url": BASE_URL + "timetable-" + page["station_id"],
        "source_html_sha256": html_sha256,
        "published_through": page["published_through"],
        "notices": page["notices"],
    }


def _load_cache(cache_path):
    cache = json.loads(Path(cache_path).read_text(encoding="utf-8"))
    if cache.get("schema_version") != 1 or cache.get("source_type") != "scheduled":
        raise ValueError("unsupported timetable cache")
    return cache


def _query_time(query_time):
    now = datetime.fromisoformat(query_time)
    if now.tzinfo is None:
        raise ValueError("query time must include a UTC offset")
    return now.astimezone(TAIPEI)


def query_departures(station_id, direction, query_time, cache_path=DEFAULT_CACHE, limit=2):
    """Read local departures for the current operating day, with no HTTP calls.

    The official table orders hours 05..23,00,01; 00/01 belong to the next
    calendar day of that service date. No unobserved weekday pattern is assumed.
    """
    if direction not in {"up", "down"}:
        raise ValueError("direction must be up (northbound) or down (southbound)")
    cache = _load_cache(cache_path)
    station_id = resolve_station(station_id, cache["stations"])
    return _query_departures(cache, station_id, direction, _query_time(query_time), limit)


def query_direct_trains(origin, destination, query_time, cache_path=DEFAULT_CACHE,
                        limit=2, rules_path=DEFAULT_RULES, boarding_buffer_minutes=3):
    """Return the next trains that stop at the destination without a transfer.

    Eligibility uses reviewed official service symbols, not guesses from nearby
    station times. No arrival time, same-train ID or transfer is inferred.
    """
    cache = _load_cache(cache_path)
    now = _query_time(query_time)
    if not isinstance(boarding_buffer_minutes, (int, float)) or not 0 <= boarding_buffer_minutes <= 60:
        raise ValueError("boarding buffer must be between 0 and 60 minutes")
    if limit < 1:
        raise ValueError("limit must be positive")
    origin = resolve_station(origin, cache["stations"])
    destination = resolve_station(destination, cache["stations"])
    details = {"destination_id": destination,
               "destination_name": cache["stations"][destination],
               "direct_only": True, "arrival_time_available": False}
    if origin == destination:
        return {"status": "same_station", "source_type": "scheduled",
                "station_id": origin, "station_name": cache["stations"][origin],
                "query_time": now.isoformat(), "next_departures": [], **details}
    try:
        rules = load_service_rules(cache["stations"], rules_path)
    except (ServiceRuleError, OSError, json.JSONDecodeError) as exc:
        return {"status": "service_rules_unavailable", "source_type": "scheduled",
                "station_id": origin, "station_name": cache["stations"][origin],
                "query_time": now.isoformat(), "next_departures": [],
                "rule_errors": [str(exc)], **details}
    order = rules["station_order"]
    direction = "down" if order.index(origin) < order.index(destination) else "up"
    result = _query_departures(cache, origin, direction, now, limit, destination, rules,
                              boarding_buffer_minutes)
    result.update(details)
    return result


def _query_departures(cache, station_id, direction, now, limit, destination=None, rules=None,
                      boarding_buffer_minutes=0):
    if limit < 1:
        raise ValueError("limit must be positive")
    service_day = (now - timedelta(hours=3)).date()
    result = {"status": "date_not_cached", "source_type": "scheduled",
              "station_id": station_id, "station_name": cache["stations"][station_id],
              "direction": direction, "query_time": now.isoformat(),
              "service_date": service_day.isoformat(), "next_departures": [],
              "service_status": "unknown", "live_disruptions_checked": False}
    entry = cache["calendar"].get(service_day.isoformat(), {}).get(station_id)
    if entry is None:
        return result
    if service_day > date.fromisoformat(entry["published_through"]):
        result["status"] = "outside_publication_horizon"
        return result
    pattern = cache["patterns"][entry["pattern_id"]]
    if pattern["station_id"] != station_id or pattern_id(pattern) != entry["pattern_id"]:
        raise ValueError("timetable pattern integrity check failed")
    table = pattern["directions"][direction]
    result.update({"direction_label": table["label"], "fetched_at": entry["fetched_at"],
                   "source_url": entry["source_url"], "notices": entry["notices"]})
    for field in ("day_type", "schedule_policy", "special_events_included",
                  "reference_service_date", "calendar_source_url"):
        if field in entry:
            result[field] = entry[field]
    rule_errors = set()
    for row in table["departures"]:
        departure = datetime.combine(service_day + timedelta(days=row["day_offset"]),
                                     time.fromisoformat(row["time"]), TAIPEI)
        if departure >= now:
            route_details = {}
            if destination is not None:
                try:
                    stops = route_for_service(rules, row["service_code"],
                                              pattern["legends"].get(row["service_code"], ""),
                                              direction, service_day.isoformat())
                    if station_id not in stops or stops[-1] == station_id:
                        raise ServiceRuleError(f"{row['service_code']} 停靠規則與起站／方向不符。")
                except ServiceRuleError as exc:
                    rule_errors.add(str(exc))
                    continue
                if destination not in stops or stops.index(destination) <= stops.index(station_id):
                    continue
                route_details = {
                    "terminal_station_id": stops[-1],
                    "terminal_station_name": cache["stations"][stops[-1]],
                    "stops_to_destination": stops[stops.index(station_id):stops.index(destination) + 1],
                    "arrival": None,
                    "route_basis": "reviewed_official_service_symbols",
                }
            result["next_departures"].append({
                "departure": departure.isoformat(), "service_code": row["service_code"],
                "train_type": SERVICE_NAMES[row["service_code"]],
                "stop_rule_text": pattern["legends"][row["service_code"]],
                **route_details,
            })
    if rule_errors:
        # An undecidable train might be earlier than the chosen ones. Do not
        # call other candidates "next", or mistake this for no direct service.
        result.update(status="service_rules_unavailable", next_departures=[],
                      rule_errors=sorted(rule_errors))
        return result
    if boarding_buffer_minutes > 0:
        cutoff = now + timedelta(minutes=boarding_buffer_minutes)
        imminent = [r for r in result["next_departures"]
                    if datetime.fromisoformat(r["departure"]) <= cutoff]
        result["next_departures"] = [r for r in result["next_departures"]
                                     if datetime.fromisoformat(r["departure"]) > cutoff]
        result.update(boarding_buffer_minutes=boarding_buffer_minutes,
                      imminent_departures=imminent, boarding_guaranteed=False)
    result["remaining_departures"] = len(result["next_departures"])
    result["next_departures"] = result["next_departures"][:limit]
    result["status"] = ("ok" if result["next_departures"] else
                        "only_imminent_departures_remaining" if result.get("imminent_departures") else
                        "no_direct_departures_remaining" if destination else "no_departures_remaining")
    return result


def format_timetable_result(result):
    """Render only the verified fields returned by the offline query."""
    station = f"{result['station_id']} {result['station_name']}"
    status = result["status"]
    if status == "same_station":
        return f"起站與目的站都是 {station}，不需要搭車。"
    if status == "date_not_cached":
        return f"本機沒有 {result['service_date']}、{station} 的班表，請更新快取後再查詢。"
    if status == "outside_publication_horizon":
        return "查詢日期超出這份班表的官方公布範圍，請更新資料後再查詢。"
    if status == "service_rules_unavailable":
        return "班表的車種或停靠規則需要重新核對，目前無法確認能到目的站的最近班次。"
    if status == "only_imminent_departures_remaining":
        return ("只剩 3 分鐘內發車的符合條件班次，時間過近，不建議趕車或奔跑。"
                "本營運日已無更晚的不換車班次，請洽站務人員確認其他方式。")
    if status == "no_direct_departures_remaining":
        return (f"依 {result['service_date']} 預定班表，{station} 到 "
                f"{result['destination_id']} {result['destination_name']} 已無後續不需換車的班次。"
                "轉乘方案尚未計算，這不代表全線停駛。")
    if status == "no_departures_remaining":
        return f"依 {result['service_date']} 預定班表，{station} 此方向已無後續預定班次。"
    if status != "ok":
        raise ValueError(f"unsupported query status {status}")
    destination = (f"到 {result['destination_id']} {result['destination_name']}"
                   if "destination_id" in result else result["direction_label"])
    basis = "一般預定班表（未納入特殊活動）" if result.get("special_events_included") is False else "預定班表"
    lines = [f"依 {result['service_date']} {basis}，{station} {destination}："]
    if result.get("imminent_departures"):
        lines.append("另有 3 分鐘內即將發車的班次，建議考慮改搭下列較晚班次，避免趕車或奔跑。")
    for index, train in enumerate(result["next_departures"]):
        label = "最近一班" if index == 0 else "下一班" if index == 1 else f"第 {index + 1} 班"
        at = datetime.fromisoformat(train["departure"]).strftime("%m/%d %H:%M")
        lines.append(f"{label} {at} 發車，{train['train_type']}。")
    if result["remaining_departures"] == 1:
        lines.append("這是此營運日最後一班符合查詢條件的班次，後面沒有下一班。")
    if "destination_id" in result:
        lines.append("以上班次依停靠規則可不換車到目的站；目前沒有抵達時間資料。")
    lines.append("時間均為臺灣時間；這是預定班表，實際運行請以現場看板為準。")
    return "\n".join(lines)
