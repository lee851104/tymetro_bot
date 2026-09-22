"""Query the downloaded timetable without connecting to the operator."""

import argparse
import json
from datetime import datetime
from pathlib import Path

from src.timetable import (DEFAULT_CACHE, TAIPEI, format_timetable_result,
                           query_departures, query_direct_trains)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--station", "--origin", dest="station", required=True,
                        help="station code or name, for example A8 or 長庚醫院")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--direction", choices=["up", "down"])
    target.add_argument("--destination", help="destination code or name; infer direction")
    parser.add_argument("--at", default=None, help="ISO 8601 including timezone; default now")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--format", choices=["json", "text"], default="json")
    args = parser.parse_args()
    at = args.at or datetime.now(TAIPEI).isoformat()
    try:
        if args.destination:
            result = query_direct_trains(args.station, args.destination, at, args.cache, args.limit)
        else:
            result = query_departures(args.station, args.direction, at, args.cache, args.limit)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(format_timetable_result(result) if args.format == "text"
          else json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
