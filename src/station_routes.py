"""Reviewed stopping rules for the official timetable's service symbols."""

import json
import re
from datetime import date
from pathlib import Path


DEFAULT_RULES = Path(__file__).resolve().parents[1] / "data/timetable/service_rules.json"
DEFAULT_ALIASES = Path(__file__).resolve().parents[1] / "data/station_aliases.json"


class StationClarificationRequired(ValueError):
    def __init__(self, question, candidates=()):
        super().__init__(question)
        self.question = question
        self.candidates = list(candidates)


class ServiceRuleError(ValueError):
    """The source no longer matches the reviewed stopping rules."""


def normalize(value):
    return re.sub(r"\s+", "", value).replace("臺", "台").casefold()


def resolve_station(value, stations, aliases_path=DEFAULT_ALIASES):
    """Resolve complete station slots using reviewed aliases; ask on ambiguity."""
    target = normalize(value)
    data = json.loads(Path(aliases_path).read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("unsupported station aliases")
    # Explicit official codes or full official names remain authoritative.
    exact = [code for code, name in stations.items()
             if target in {normalize(code), normalize(name), normalize(name.removesuffix("站"))}]
    if len(exact) == 1:
        return exact[0]
    for entry in data["clarifications"]:
        if target in {normalize(term) for term in entry["terms"]}:
            raise StationClarificationRequired(entry["question"], entry["candidates"])
    matches = []
    for code, name in stations.items():
        aliases = {code, name, name.removesuffix("站"), code + name,
                   code + name.removesuffix("站")}
        aliases.update(data["aliases"].get(code, []))
        if target in {normalize(alias) for alias in aliases}:
            matches.append(code)
    if not matches:
        codes = re.findall(r"a\d+a?", target)
        if codes:
            canonical = {normalize(c): c for c in stations}
            known = [canonical[c] for c in codes if c in canonical]
            if known:
                raise StationClarificationRequired("站碼與站名無法一致辨識，請確認起訖站的站碼或完整站名。", known)
    if len(matches) != 1:
        raise ValueError(f"無法辨識車站「{value}」，請使用現有站代碼或完整站名。")
    return matches[0]


def load_service_rules(stations, path=DEFAULT_RULES):
    rules = json.loads(Path(path).read_text(encoding="utf-8"))
    order = rules.get("station_order", [])
    if (rules.get("schema_version") != 1 or len(set(order)) != len(order)
            or set(order) != set(stations)):
        raise ServiceRuleError("站點清單已改變，須重新核對停靠規則。")
    for code, service in rules.get("services", {}).items():
        if not service.get("source_legend") or not service.get("routes"):
            raise ServiceRuleError(f"{code} 缺少來源圖例或停靠站。")
        for direction, stops in service["routes"].items():
            if (direction not in {"up", "down"} or len(stops) < 2
                    or len(set(stops)) != len(stops) or not set(stops) <= set(order)):
                raise ServiceRuleError(f"{code} 的停靠站設定無效。")
            indices = [order.index(stop) for stop in stops]
            if indices != sorted(indices, reverse=direction == "up"):
                raise ServiceRuleError(f"{code} 的停靠站順序與方向不符。")
    return rules


def route_for_service(rules, code, source_legend, direction, service_day):
    service = rules["services"].get(code)
    if not service or normalize(service["source_legend"]) != normalize(source_legend):
        raise ServiceRuleError(f"{code} 的官網圖例未經核對或已有變更。")
    day = date.fromisoformat(service_day)
    if (("valid_from" in service and day < date.fromisoformat(service["valid_from"]))
            or ("valid_through" in service
                and day > date.fromisoformat(service["valid_through"]))):
        raise ServiceRuleError(f"{code} 超出已核對的活動日期。")
    stops = service["routes"].get(direction)
    if not stops:
        raise ServiceRuleError(f"{code} 沒有此方向的已核對停靠規則。")
    return stops
