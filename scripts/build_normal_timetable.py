"""Build the user-selected normal timetable without special-event services."""

import argparse
import copy
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

from src.service_calendar import expand_calendar
from src.timetable import pattern_id

ROOT = Path(__file__).resolve().parents[1]
POLICY = "normal_dgpa_calendar_no_special_events"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_cache(weekday, holiday, calendar, start, days):
    references = {"workday": (weekday, "2026-09-21"), "holiday": (holiday, "2026-10-17")}
    if days < 1 or start < date(2026, 9, 21):
        raise ValueError("normal timetable starts on 2026-09-21; days must be positive")
    if weekday["stations"] != holiday["stations"]:
        raise ValueError("reference station lists disagree")
    result = {"schema_version": 1, "source_type": "scheduled", "timezone": "Asia/Taipei",
              "service_day_cutoff_hour": 3, "stations": weekday["stations"],
              "schedule_policy": POLICY, "special_events_included": False,
              "image_revision": "2026-09-21", "patterns": {}, "calendar": {},
              "calendar_source_url": calendar["source_url"]}
    for offset in range(days):
        day = (start + timedelta(days=offset)).isoformat()
        if day not in calendar["dates"]:
            raise ValueError(f"no reviewed calendar for {day}")
        kind = calendar["dates"][day]["day_type"]
        reference, reference_day = references[kind]
        if set(reference["calendar"][reference_day]) != set(result["stations"]):
            raise ValueError("incomplete reference day")
        entries = {}
        for station, source in reference["calendar"][reference_day].items():
            if day > source["published_through"]:
                raise ValueError(f"{day} exceeds source publication horizon")
            original = reference["patterns"][source["pattern_id"]]
            if pattern_id(original) != source["pattern_id"] or original["station_id"] != station:
                raise ValueError("reference pattern integrity check failed")
            pattern = copy.deepcopy(original)
            # No activity services may slip into a supposedly normal reference.
            for table in pattern["directions"].values():
                if any(row["service_code"] in {"des06", "des07"} for row in table["departures"]):
                    raise ValueError("reference contains special-event services")
                table["source_notes"] = {k: v for k, v in table["source_notes"].items()
                                         if k not in {"des06", "des07"}}
            pattern["legends"] = {k: v for k, v in pattern["legends"].items()
                                  if k not in {"des06", "des07"}}
            key = pattern_id(pattern)
            result["patterns"][key] = pattern
            entries[station] = {
                "pattern_id": key, "fetched_at": source["fetched_at"],
                "source_url": source["source_url"],
                "published_through": source["published_through"],
                "notices": ["依使用者指定的一般平假日班表，未納入特殊活動調整。"],
                "day_type": kind, "schedule_policy": POLICY, "special_events_included": False,
                "reference_service_date": reference_day,
                "reference_source_html_sha256": source["source_html_sha256"],
                "calendar_source_url": calendar["source_url"],
                "calendar_source_sha256": calendar["source_sha256"],
            }
        result["calendar"][day] = entries
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2026, 9, 21))
    parser.add_argument("--days", type=int, default=14)
    args = parser.parse_args()
    folder = ROOT / "data/timetable"
    rules_path = folder / "sources/dgpa_2026_rules.json"
    rules = read_json(rules_path)
    if hashlib.sha256((ROOT / rules["source_file"]).read_bytes()).hexdigest() != rules["source_sha256"]:
        raise ValueError("calendar PDF hash mismatch")
    calendar = expand_calendar(rules)
    weekday = read_json(folder / "official_cache.json")
    holiday = read_json(folder / "sources/official_holiday_2026-10-17.json")
    cache = build_cache(weekday, holiday, calendar, args.start, args.days)
    sources = [rules_path, folder / "sources/dgpa_2026.pdf", folder / "official_cache.json",
               folder / "sources/official_holiday_2026-10-17.json",
               folder / "sources/time_2026-09-21.json", ROOT / "scripts/build_normal_timetable.py",
               ROOT / "src/service_calendar.py"]
    cache["build_sources_sha256"] = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in sources}
    write_json(folder / "calendar_2026.json", calendar)
    write_json(folder / "cache.json", cache)
    print(f"Built {len(calendar['dates'])} calendar dates; {len(cache['calendar'])} service dates; "
          f"{len(cache['patterns'])} patterns; special events excluded")


if __name__ == "__main__":
    main()
