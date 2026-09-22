"""Explicit-year workday/holiday classification from a reviewed DGPA calendar."""

import json
from datetime import date, timedelta
from pathlib import Path

DEFAULT_CALENDAR = Path(__file__).resolve().parents[1] / "data/timetable/calendar_2026.json"


def expand_calendar(rules):
    if rules.get("schema_version") != 1:
        raise ValueError("unsupported calendar rules")
    year = rules["year"]
    holidays = rules["extra_holidays"]
    workdays = rules["working_day_overrides"]
    if set(holidays) & set(workdays):
        raise ValueError("conflicting holiday/workday overrides")
    for value in set(holidays) | set(workdays):
        if date.fromisoformat(value).year != year:
            raise ValueError("calendar override outside source year")
    days = {}
    day = date(year, 1, 1)
    while day.year == year:
        key = day.isoformat()
        if key in workdays:
            kind, reason = "workday", "working_day_override"
        elif key in holidays:
            kind, reason = "holiday", "published_holiday"
        elif day.weekday() in rules["weekend_days"]:
            kind, reason = "holiday", "weekend"
        else:
            kind, reason = "workday", "regular_workday"
        days[key] = {"day_type": kind, "reason": reason}
        day += timedelta(days=1)
    return {"schema_version": 1, "year": year, "source_url": rules["source_url"],
            "source_sha256": rules["source_sha256"], "dates": days}


def classify_service_date(service_date, calendar_path=DEFAULT_CALENDAR):
    """Use the operating date; never extrapolate an unprovided calendar year."""
    key = date.fromisoformat(service_date).isoformat()
    calendar = json.loads(Path(calendar_path).read_text(encoding="utf-8"))
    if calendar.get("schema_version") != 1 or key not in calendar["dates"]:
        raise ValueError(f"calendar does not cover {key}")
    return calendar["dates"][key]["day_type"]
