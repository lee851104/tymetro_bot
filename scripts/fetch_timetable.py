"""Download official date-specific station tables into an offline JSON cache."""

import argparse
import hashlib
import json
import time
from datetime import date, datetime, timedelta
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from src.timetable import BASE_URL, OFFICIAL_CACHE, TAIPEI, add_page, parse_timetable


def fetch(opener, url, data=None, service_date=None):
    headers = {"User-Agent": "tymetro-bot-timetable-cache/1.0"}
    if service_date is not None:
        # The site's date-selector endpoint sets this public preference cookie
        # with Max-Age=10. Renew its value explicitly for every page request so
        # a batch cannot silently revert to today's timetable after 10 seconds.
        headers["Cookie"] = "tymetro_new_chdate=" + date.fromisoformat(str(service_date)).isoformat()
    request = Request(url, data=data, headers=headers)
    for attempt in range(3):
        try:
            with opener.open(request, timeout=30) as response:
                return response.read().decode("utf-8-sig")
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def atomic_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=datetime.now(TAIPEI).date())
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--output", type=Path, default=OFFICIAL_CACHE)
    parser.add_argument("--raw-dir", type=Path, default=Path("outputs/timetable_raw"))
    parser.add_argument("--delay", type=float, default=0.4, help="seconds between requests")
    parser.add_argument("--refresh", action="store_true", help="replace locally saved source pages")
    args = parser.parse_args()
    if args.days < 1 or args.delay < 0.2:
        parser.error("days must be positive and delay must be at least 0.2 seconds")
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    # Use the public date selector endpoint, exactly as the site's JS does.
    def select_day(day):
        fetch(opener, BASE_URL + "station-timetable-date.php",
              urlencode({"date": day.isoformat()}).encode())
        time.sleep(args.delay)

    select_day(args.start)
    first_html = fetch(opener, BASE_URL + "timetable-A1", service_date=args.start)
    first_page = parse_timetable(first_html, "A1", args.start.isoformat())
    end = args.start + timedelta(days=args.days - 1)
    if end > date.fromisoformat(first_page["published_through"]):
        parser.error(f"requested end {end} exceeds official horizon {first_page['published_through']}")
    cache = {"schema_version": 1, "source_type": "scheduled", "timezone": "Asia/Taipei",
             "service_day_cutoff_hour": 3, "stations": {}, "patterns": {}, "calendar": {}}
    if args.output.exists():
        cache = json.loads(args.output.read_text(encoding="utf-8"))
        if cache.get("schedule_policy"):
            parser.error("refusing to overwrite a generated policy cache; download to official_cache.json")
        if cache.get("schema_version") != 1:
            parser.error("existing cache has an unsupported schema")
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    for offset in range(args.days):
        day = args.start + timedelta(days=offset)
        select_day(day)
        for station in first_page["stations"]:
            raw_path = args.raw_dir / f"{day}-{station}.html"
            meta_path = raw_path.with_suffix(".json")
            if raw_path.exists() and meta_path.exists() and not args.refresh:
                html = raw_path.read_bytes().decode("utf-8")
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                fetched_at = meta["fetched_at"]
                if hashlib.sha256(html.encode()).hexdigest() != meta["sha256"]:
                    raise ValueError(f"raw cache hash mismatch: {raw_path}")
            else:
                time.sleep(args.delay)
                html = fetch(opener, BASE_URL + "timetable-" + station, service_date=day)
                fetched_at = datetime.now(TAIPEI).isoformat(timespec="seconds")
                # Never persist an error page or the wrong date as valid data.
                parse_timetable(html, station, day.isoformat())
                raw_path.write_bytes(html.encode("utf-8"))
                atomic_write(meta_path, {"fetched_at": fetched_at,
                                        "sha256": hashlib.sha256(html.encode()).hexdigest()})
            page = parse_timetable(html, station, day.isoformat())
            add_page(cache, page, fetched_at, hashlib.sha256(html.encode()).hexdigest())
        # A failed fetch leaves the previous complete dates intact. Raw pages
        # support a resumable retry without downloading completed work again.
        used = {entry["pattern_id"] for items in cache["calendar"].values() for entry in items.values()}
        cache["patterns"] = {key: value for key, value in cache["patterns"].items() if key in used}
        cache["updated_at"] = datetime.now(TAIPEI).isoformat(timespec="seconds")
        atomic_write(args.output, cache)
        count = sum(len(direction["departures"]) for sid in first_page["stations"]
                    for direction in cache["patterns"][cache["calendar"][str(day)][sid]["pattern_id"]]["directions"].values())
        print(f"{day}: {len(first_page['stations'])} stations, {count} departures; {len(cache['patterns'])} distinct patterns", flush=True)
    print(f"Saved {len(cache['calendar'])} dates to {args.output}")


if __name__ == "__main__":
    main()
