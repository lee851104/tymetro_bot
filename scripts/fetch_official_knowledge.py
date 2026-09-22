"""Archive official static service sources with links, structure and provenance.

Snapshots are source material, not automatically approved answers. Some official
pages contain expired promotions or link to live systems operated elsewhere.
"""

import argparse
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from src.timetable import Document, Node, TAIPEI, clean

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://www.tymetro.com.tw/tymetro-new/tw/_pages/"
PAGES = [
    ("single_tickets", "單程票與一日票", "travel-guide/ticketson01.php"),
    ("electronic_tickets", "電子票證", "travel-guide/ticketson03.php"),
    ("passenger_rules", "乘車與自行車規則", "travel-guide/notice.html"),
    ("accessible", "無障礙服務", "travel-guide/accessible.html"),
    ("transfer", "轉乘與停車資訊", "travel-guide/transfer.html"),
    ("checkin_overview", "預辦登機簡介", "checkin/index.html"),
    ("checkin_process", "預辦登機流程", "checkin/process.html"),
    ("fare_timetable_query", "票價與時刻查詢入口", "travel-guide/timetable-search.html"),
    ("faq", "常見問題", "service/FAQ.html"),
    ("lost_property", "遺失物查詢", "service/lost.html"),
]


def text_content(node):
    if isinstance(node, str):
        return node
    if node.tag in {"script", "style", "nav", "footer"}:
        return ""
    text = " ".join(text_content(child) for child in node.children)
    return text + ("\n" if node.tag in {"p", "li", "tr", "h1", "h2", "h3", "h4", "div"} else " ")


def extract(html, url):
    doc = Document(html).root
    containers = [n for n in doc.find("div") if n.attrs.get("class") == "main"]
    if len(containers) != 1:
        raise ValueError("expected one main content container")
    main = containers[0]
    lines = [clean(line) for line in text_content(main).splitlines() if clean(line)]
    if len(" ".join(lines)) < 100:
        raise ValueError("empty main content")
    return {"headings": [clean(h.text()) for h in main.find() if h.tag in {"h1", "h2", "h3", "h4"}],
            "text_lines": lines,
            "links": [{"label": clean(a.text()), "url": urljoin(url, a.attrs["href"])}
                      for a in main.find("a") if a.attrs.get("href")
                      and not a.attrs["href"].startswith(("javascript:", "mailto:", "tel:"))],
            "images": [{"alt": n.attrs.get("alt", ""), "url": urljoin(url, n.attrs["src"])}
                       for n in main.find("img") if n.attrs.get("src")]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    output = ROOT / "data/knowledge"
    raw = ROOT / "outputs/knowledge_raw"
    output.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)
    stations = json.loads((ROOT / "data/timetable/cache.json").read_text(encoding="utf-8"))["stations"]
    pages = PAGES + [("station_" + s, s + " " + name, "travel-guide/" + s) for s, name in stations.items()]
    records = []
    for key, title, relative in pages:
        url = BASE + relative
        raw_path, meta_path = raw / (key + ".html"), raw / (key + ".json")
        if raw_path.exists() and meta_path.exists() and not args.refresh:
            payload = raw_path.read_bytes()
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if hashlib.sha256(payload).hexdigest() != meta["sha256"] or meta["url"] != url:
                raise ValueError("saved source changed")
        else:
            time.sleep(0.4)
            with urlopen(Request(url, headers={"User-Agent": "tymetro-bot-source-audit/1.0"}), timeout=30) as response:
                if urlsplit(response.url).hostname != "www.tymetro.com.tw":
                    raise ValueError("unexpected source redirect")
                payload = response.read()
            extract(payload.decode("utf-8-sig"), url)
            meta = {"url": url, "fetched_at": datetime.now(TAIPEI).isoformat(timespec="seconds"),
                    "sha256": hashlib.sha256(payload).hexdigest()}
            raw_path.write_bytes(payload)
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        records.append({"id": key, "title": title, **meta, "answer_ready": False,
                        "review_required": "核對適用期限、完整條件、圖表及連結內容後才可作回答依據。",
                        **extract(payload.decode("utf-8-sig"), url)})
    bundle = {"schema_version": 1, "purpose": "official_source_inventory_not_unfiltered_training_data",
              "pages": records}
    temporary = output / "official_sources.json.tmp"
    temporary.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output / "official_sources.json")
    print(f"Saved {len(records)} official source pages, including {len(stations)} station pages.")


if __name__ == "__main__":
    main()
