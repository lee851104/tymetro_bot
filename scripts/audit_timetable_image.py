"""Compare manually transcribed image evidence with the dated departure cache.

This audits the explicit scope recorded in the image JSON, not every pixel or
every holiday. It never silently replaces conflicting data or extrapolates dates.
"""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/timetable/sources/time_2026-09-21.json"


def hhmm(value):
    if len(value) != 4 or not value.isdigit():
        raise ValueError(f"invalid time: {value}")
    hour, minute = int(value[:2]), int(value[2:])
    if hour > 23 or minute > 59:
        raise ValueError(f"invalid time: {value}")
    return f"{hour:02}:{minute:02}"


def audit(source, cache, service_date=None, day_type="workday"):
    day = service_date or source["reference_service_date"]
    if day_type not in {"workday", "holiday"}:
        raise ValueError("unknown day type")
    results = []

    def departures(station, direction):
        entry = cache["calendar"][day][station]
        return cache["patterns"][entry["pattern_id"]]["directions"][direction]["departures"]

    def record(group, station, direction, expected, actual):
        results.append({"group": group, "station": station, "direction": direction,
                        "expected": expected, "actual": actual, "matches": expected == actual})

    for direction in ("down", "up"):
        for family, codes in (("local", {"des03"}), ("express", {"des01", "des02"})):
            seeds = source["periodic_departures"][direction][family + "_minute_seed"]
            for station, seed in seeds.items():
                minutes = sorted((seed + 15 * n) % 60 for n in range(4))
                for hour in source["periodic_departures"]["audit_hours"]:
                    expected = [f"{hour:02}:{minute:02}" for minute in minutes]
                    actual = sorted(row["time"] for row in departures(station, direction)
                                    if row["service_code"] in codes and row["day_offset"] == 0
                                    and row["time"].startswith(f"{hour:02}:"))
                    record("periodic_" + family, station, direction, expected, actual)
            for station, value in source["first_departures"][direction][family].items():
                actual = [row["time"] for row in departures(station, direction)
                          if row["service_code"] in codes]
                record("first_" + family, station, direction, hhmm(value), actual[0] if actual else None)

    for row in source["explicit_departure_rows"]:
        if row["condition"] == "weekday" and day_type == "holiday":
            continue
        for station, value in row["times"].items():
            at = hhmm(value)
            actual = sorted(d["service_code"] for d in departures(station, row["direction"])
                            if d["time"] == at and d["day_offset"] == int(int(value[:2]) < 3))
            # A different service can share the minute; the source service must exist.
            record(row["id"], station, row["direction"], row["service_code"],
                   row["service_code"] if row["service_code"] in actual else actual)

    a1 = source["a1"]
    expected = {(hhmm(a1["express_first"]), "des01")}
    for start, end, code in ((a1["express_regular_start"], a1["express_regular_end"], "des01"),
                             (a1["local_regular_start"], a1["local_regular_end"], "des03")):
        begin = int(start[:2]) * 60 + int(start[2:])
        finish = int(end[:2]) * 60 + int(end[2:])
        for value in range(begin, finish + 1, a1["interval_minutes"]):
            expected.add((f"{value // 60:02}:{value % 60:02}", code))
    for value in a1["weekday_extended_express" if day_type == "workday" else "holiday_extended_express"]:
        expected.remove((hhmm(value), "des01"))
        expected.add((hhmm(value), "des02"))
    extra = a1["weekday_airport_extra"] if day_type == "workday" else []
    for value in extra + a1["daily_airport_last"]:
        expected.add((hhmm(value), "des04"))
    actual = {(row["time"], row["service_code"]) for row in departures("A1", "down")}
    record("A1_complete_" + day_type, "A1", "down", sorted(expected), sorted(actual))

    extended = source["extended_express"]
    selected = (("down", ["down_weekday"]),
                ("up", ["up_weekday_morning", "up_daily_evening", "up_weekday_evening"]))
    if day_type == "holiday":
        selected = (("down", ["down_holiday"]), ("up", ["up_holiday", "up_daily_evening"]))
    for direction, groups in selected:
        for group in groups:
            for row in extended[group]:
                if group == "up_weekday_morning" and row[0] == "0700":
                    continue  # IMG-02 resolved by user: main-table des05 wins.
                for station, value in zip(extended[direction + "_columns"], row, strict=True):
                    if value is None or station.endswith("_arrival"):
                        continue
                    actual = [d["service_code"] for d in departures(station, direction)
                              if d["time"] == hhmm(value) and d["day_offset"] == 0]
                    record(group + "-" + (row[0] or "initial"), station, direction,
                           "des02", "des02" if "des02" in actual else actual)

    return {"reference_service_date": day, "day_type": day_type, "checks": len(results),
            "passed": sum(r["matches"] for r in results),
            "differences": [r for r in results if not r["matches"]],
            "covered_stations": sorted({r["station"] for r in results}, key=lambda s: (int(s[1:].rstrip("a")), s)),
            "scope": "A1 全日；全線首班與 10–15 時基本頻率；已轉錄的適用加班、末班、北上夜間及增停發車格。",
            "not_verified": ["全圖每一格", "圖片中到站／終點抵達時間與車次串接"],
            "unresolved": source["unresolved"]}


def main():
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    image = ROOT / source["image_path"]
    if hashlib.sha256(image.read_bytes()).hexdigest() != source["image_sha256"]:
        raise ValueError("source image hash mismatch")
    cache_path = ROOT / "data/timetable/cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    results = [audit(source, cache), audit(source, cache, "2026-09-25", "holiday")]
    report = {"checks": sum(r["checks"] for r in results), "passed": sum(r["passed"] for r in results),
              "differences": [d for r in results for d in r["differences"]], "results": results,
              "resolved": source.get("resolved", []), "unresolved": source["unresolved"]}
    report["source_json_sha256"] = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    report["cache_sha256"] = hashlib.sha256(cache_path.read_bytes()).hexdigest()
    output = ROOT / "reports/timetable_image_audit.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["differences"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
