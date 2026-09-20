"""Deterministic journey selection for synthetic schedule fixtures.

This module does not contact the operator or provide live departure times.
"""

from datetime import datetime, timedelta


def _time(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamps must contain a UTC offset")
    return parsed


def _empty(status, origin, destination, query_time, fetched_at, source_type):
    return {
        "status": status,
        "origin": origin,
        "destination": destination,
        "query_time": query_time,
        "fetched_at": fetched_at,
        "source_type": source_type,
        "service_status": "unknown" if status in {"unavailable", "stale_data"} else "normal",
        "next_trains": [],
    }


def get_next_trains(origin, destination, query_time, journeys, fetched_at,
                    source_type, max_age_minutes=15):
    """Return up to two eligible journeys ordered by first departure.

    ``journeys`` contains candidate paths with one or more legs. A leg lists
    actual stops; naming a destination alone does not make it reachable.
    Times and data freshness use offset-aware ISO 8601 values.
    """
    if source_type not in {"scheduled", "realtime"}:
        raise ValueError("source_type must be scheduled or realtime")
    now = _time(query_time)
    fetched = _time(fetched_at)
    result = _empty("unavailable", origin, destination, query_time,
                    fetched_at, source_type)
    if journeys is None:
        return result
    if fetched > now or now - fetched > timedelta(minutes=max_age_minutes):
        result["status"] = "stale_data"
        result["service_status"] = "unknown"
        return result

    candidates = []
    for journey in journeys:
        legs = journey.get("legs", [])
        if not legs or legs[0].get("origin") != origin:
            continue
        if legs[-1].get("destination") != destination:
            continue
        selected = []
        previous_arrival = None
        valid = True
        transfer_wait = 0
        transfer_stations = []
        for index, leg in enumerate(legs):
            stops = leg.get("stops", [])
            start = leg.get("origin")
            end = leg.get("destination")
            if (leg.get("status") in {"cancelled", "suspended"}
                    or start not in stops or end not in stops
                    or stops.index(start) >= stops.index(end)):
                valid = False
                break
            departure = _time(leg.get("updated_departure", leg["departure"]))
            arrival = _time(leg.get("updated_arrival", leg["arrival"]))
            if arrival <= departure:
                valid = False
                break
            if index and (legs[index - 1]["destination"] != start
                          or departure < previous_arrival):
                valid = False
                break
            if index:
                transfer_wait += int((departure - previous_arrival).total_seconds() // 60)
                transfer_stations.append(start)
            selected.append({
                "train_id": leg["train_id"],
                "train_type": leg["train_type"],
                "origin": start,
                "destination": end,
                "direction": leg.get("direction", f"往{end}"),
                "departure": departure.isoformat(),
                "arrival": arrival.isoformat(),
                "status": leg.get("status", "normal"),
            })
            previous_arrival = arrival
        if valid and selected and _time(selected[0]["departure"]) >= now:
            candidates.append({
                "departure": selected[0]["departure"],
                "arrival": selected[-1]["arrival"],
                "transfer_wait_minutes": transfer_wait,
                "transfer_stations": transfer_stations,
                "legs": selected,
            })

    candidates.sort(key=lambda item: (_time(item["departure"]),
                                      _time(item["arrival"])))
    result["status"] = "ok" if candidates else "no_service"
    result["next_trains"] = candidates[:2]
    has_cancellation = any(leg.get("status") in {"cancelled", "suspended"}
                           for journey in journeys for leg in journey.get("legs", []))
    if has_cancellation and not candidates:
        result["service_status"] = "suspended"
    elif any(leg["status"] == "delayed" for item in result["next_trains"]
           for leg in item["legs"]):
        result["service_status"] = "delayed"
    elif has_cancellation:
        result["service_status"] = "partial_disruption"
    else:
        result["service_status"] = "normal"
    return result
