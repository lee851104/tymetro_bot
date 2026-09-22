"""Application grounding; the frozen training/evaluation contract stays unchanged.

Model text is diagnostic evidence, never evidence that a train exists or does
not exist. Resolve complete route slots, then render reviewed timetable facts.
"""

import json
import re
import sys
import unicodedata
from datetime import datetime, timedelta

from src.bot_tools import get_next_trains, render_answer
from src.demo_chat import _parse_route, resolve_demo_station
from src.station_routes import StationClarificationRequired
from src.timetable import DEFAULT_CACHE, TAIPEI, query_direct_trains

TRAIN_CODES = {
    '普通車': {'des03', 'des04', 'des05', 'des06', 'des07'},
    '直達車': {'des01', 'des02'},
}
BOUNDARY_PATTERNS = {
    'last': r'末班(?:車)?|最後一班(?:車)?|最晚(?:一班)?(?:車)?',
    'first': r'首班(?:車)?|第一班(?:車)?|最早(?:一班)?(?:車)?',
}
CLARIFY = '請提供起站與目的站，例如「台北車站到第二航廈，下一班普通車幾點？」；查詢日期與時間可在表單設定。尚未確認班表前，我不能判定有沒有車。'


def validate_form_route(route):
    """The visual picker sends canonical IDs, not text for the model to guess."""
    if not isinstance(route, dict) or set(route) - {'origin', 'destination', 'train_type'}:
        raise ValueError('Invalid route')
    stations = json.loads(DEFAULT_CACHE.read_text(encoding='utf-8'))['stations']
    if any(not isinstance(route.get(k), str) or route[k] not in stations for k in ('origin', 'destination')):
        raise ValueError('Select existing station codes')
    if route.get('train_type') not in (None, '普通車', '直達車'):
        raise ValueError('Select a supported train type')
    return route


def query_trains(origin, destination, at, train_type=None):
    """Filter the entire eligible service day, BEFORE buffer/count/top two."""
    result = get_next_trains(origin, destination, at)
    if train_type is None:
        return result
    if train_type not in TRAIN_CODES:
        raise ValueError('unsupported train type')
    result['requested_train_type'] = train_type
    if result['status'] not in {'ok', 'only_imminent_departures_remaining', 'no_direct_departures_remaining'}:
        return result
    try:
        raw = query_direct_trains(origin, destination, at, limit=sys.maxsize, boarding_buffer_minutes=0)
    except (OSError, ValueError, KeyError, TypeError):
        return {**result, 'status': 'unavailable', 'next_trains': [], 'imminent_departures': [],
                'remaining_departures': 0}
    if raw['status'] not in {'ok', 'no_direct_departures_remaining'}:
        return {**result, 'status': raw['status'], 'next_trains': [], 'imminent_departures': [],
                'remaining_departures': 0}
    eligible = [r for r in raw['next_departures'] if r['service_code'] in TRAIN_CODES[train_type]]
    cutoff = datetime.fromisoformat(at) + timedelta(minutes=3)
    imminent = [r['departure'] for r in eligible if datetime.fromisoformat(r['departure']) <= cutoff]
    later = [r for r in eligible if datetime.fromisoformat(r['departure']) > cutoff]
    result.update(
        status='ok' if later else 'only_imminent_departures_remaining' if imminent else 'no_direct_departures_remaining',
        remaining_departures=len(later), imminent_departures=imminent,
        next_trains=[{'departure': r['departure'], 'train_type': r['train_type'],
                      'terminal': r['terminal_station_id']} for r in later[:2]],
    )
    return result


def query_service_boundary(origin, destination, at, mode, train_type=None, service_date=None):
    """Find a day's first/last eligible train, including its post-midnight rows.

    Keep this application feature outside the frozen model tool contract.
    The 3-minute policy annotates the answer; it must not hide the actual last
    train or relabel a later departure as the first train.
    """
    if mode not in BOUNDARY_PATTERNS or train_type not in (None, *TRAIN_CODES):
        raise ValueError('unsupported boundary query')
    moment = datetime.fromisoformat(at)
    if moment.tzinfo is None:
        raise ValueError('query time must include a UTC offset')
    moment = moment.astimezone(TAIPEI)
    day = datetime.fromisoformat(service_date).date() if service_date else (moment - timedelta(hours=3)).date()
    start = datetime.combine(day, datetime.min.time(), TAIPEI) + timedelta(hours=3)
    result = {'status': 'unavailable', 'origin': origin, 'destination': destination,
              'query_time': moment.isoformat(), 'service_date': day.isoformat(),
              'query_mode': mode, 'requested_train_type': train_type,
              'source_type': 'scheduled', 'service_status': 'unknown',
              'direct_only': True, 'arrival_time_available': False,
              'next_trains': [], 'imminent_departures': [], 'remaining_departures': 0,
              'boarding_buffer_minutes': 3, 'boarding_guaranteed': False}
    try:
        raw = query_direct_trains(origin, destination, start.isoformat(),
                                  limit=sys.maxsize, boarding_buffer_minutes=0)
    except (OSError, ValueError, KeyError, TypeError):
        return result
    result.update(status=raw['status'], origin=raw['station_id'], destination=raw['destination_id'])
    for field in ('service_date', 'fetched_at', 'day_type', 'schedule_policy', 'special_events_included'):
        if field in raw:
            result[field] = raw[field]
    if raw['status'] not in {'ok', 'no_direct_departures_remaining'}:
        return result
    rows = [r for r in raw['next_departures'] if train_type is None or r['service_code'] in TRAIN_CODES[train_type]]
    rows.sort(key=lambda r: datetime.fromisoformat(r['departure']))
    result['matching_departures'] = len(rows)
    if not rows:
        result['status'] = 'no_matching_departures'
        return result
    chosen_time = rows[0 if mode == 'first' else -1]['departure']
    chosen = [r for r in rows if r['departure'] == chosen_time]
    seconds = (datetime.fromisoformat(chosen_time) - moment).total_seconds()
    result.update(status='ok',
                  departure_state='passed' if seconds < 0 else 'imminent' if seconds <= 180 else 'upcoming',
                  remaining_departures=sum(datetime.fromisoformat(r['departure']) > moment + timedelta(minutes=3) for r in rows),
                  next_trains=[{'departure': r['departure'], 'train_type': r['train_type'],
                                'terminal': r['terminal_station_id']} for r in chosen])
    return result


def render_grounded(result):
    kind = result.get('requested_train_type')
    mode = result.get('query_mode')
    if mode in BOUNDARY_PATTERNS:
        label = '末班車' if mode == 'last' else '首班車'
        if result['status'] == 'no_matching_departures':
            return (f"依 {result['service_date']} 營運日的一般預定班表，查不到從 {result['origin']} 到 "
                    f"{result['destination']} 不換車的{kind or '列車'}班次，因此無法列出{label}。"
                    '這只限本次日期、方向與車種；尚未計算轉乘方案。')
        if result['status'] == 'ok':
            trains = '；'.join(
                f"{datetime.fromisoformat(t['departure']).strftime('%m/%d %H:%M')} 發車，{t['train_type']}"
                for t in result['next_trains'])
            text = (f"依 {result['service_date']} 營運日的一般預定班表，{result['origin']} 到 "
                    f"{result['destination']} 不需換車的{kind or ''}{label}：{trains}（臺灣時間）。"
                    f"列車會停靠 {result['destination']}，請在該站下車。")
            if result['next_trains'][0]['departure'][:10] != result['service_date']:
                text += '這班於隔日凌晨發車，仍屬上述營運日。'
            if result['departure_state'] == 'passed':
                text += '相對於本次查詢時間，這班預定發車時間已過。'
                if mode == 'last':
                    text += '本營運日沒有更晚的符合條件班次；請洽站務人員確認替代交通。'
            elif result['departure_state'] == 'imminent':
                text += '距離本次查詢時間僅剩 3 分鐘內，不建議趕車或奔跑。'
                text += ('本營運日沒有更晚的符合條件班次；請洽站務人員確認替代交通。'
                         if mode == 'last' else '可另查後續班次。')
            return text + '不含特殊活動；實際運行以現場看板為準。'
    if kind and result['status'] == 'no_direct_departures_remaining':
        at = datetime.fromisoformat(result['query_time']).strftime('%m/%d %H:%M')
        return (f"依預定班表，{at}（臺灣時間）之後，本營運日查不到從 {result['origin']} 到 "
                f"{result['destination']} 不換車的{kind}班次。這只限本次日期、時間、方向及車種，"
                '不代表這個站沒有普通車服務。實際運行請以現場看板為準。')
    text = render_answer(result)
    if kind and result['status'] == 'only_imminent_departures_remaining':
        text = f'你指定的是{kind}。' + text
    if result['status'] == 'ok':
        text += f"上述列車都會停靠 {result['destination']}，請在該站下車；列車終點不是唯一停靠站。"
    return text


def _time_and_text(text, at):
    """Support explicit numeric departure dates/times; never silently discard others."""
    moment = datetime.fromisoformat(at)
    dates = list(re.finditer(r'(?<!\d)(?:(\d{4})[-/年])?(\d{1,2})[-/月](\d{1,2})(?:日|號)?(?!\d)', text))
    relatives = re.findall(r'今天|明天|後天|昨天', text)
    clock_text = text
    for match in dates:
        clock_text = clock_text[:match.start()] + ' ' * len(match[0]) + clock_text[match.end():]
    clocks = list(re.finditer(r'(?<![A-Za-z\d])(?:(凌晨|早上|上午|中午|下午|晚上)\s*)?(\d{1,2})(?:[:：](\d{2})|點(?:(\d{1,2})分?|(半))?)(?!\d)', clock_text))
    if len(dates) + len(relatives) > 1 or len(clocks) > 1:
        raise ValueError('請指定一個出發日期與時間，或用表單設定後只輸入起訖站與車種。')
    if dates:
        match = dates[0]
        moment = moment.replace(year=int(match[1] or moment.year), month=int(match[2]), day=int(match[3]))
    elif relatives:
        moment += timedelta(days={'今天': 0, '明天': 1, '後天': 2, '昨天': -1}[relatives[0]])
    if clocks:
        match = clocks[0]
        period, hour = match[1], int(match[2])
        minute = int(match[3] or match[4] or (30 if match[5] else 0))
        if period:
            if not 1 <= hour <= 12:
                raise ValueError('請用 24 小時制指定時間，例如 10:00 或 22:00。')
            if period in {'下午', '晚上', '中午'}:
                hour = hour % 12 + 12
            else:
                hour %= 12
        moment = moment.replace(hour=hour, minute=minute, second=0, microsecond=0)
    for match in sorted(dates + clocks, key=lambda m: m.start(), reverse=True):
        text = text[:match.start()] + text[match.end():]
    text = re.sub(r'今天|明天|後天|昨天', '', text)
    if re.search(r'早上|上午|下午|晚上|中午|凌晨|週|星期|禮拜|\d.*(?:時|分)|[一二三四五六七八九十兩]+點|\d{1,2}[:：]\d', text):
        raise ValueError('這個日期或時間還無法可靠辨識。請在表單設定後，只輸入起訖站與車種。')
    if '現在' in text:
        if dates or relatives or clocks:
            raise ValueError('請確認要查現在，還是你指定的日期與時間。')
        moment = datetime.now(TAIPEI)
        text = text.replace('現在', '')
    return moment.isoformat(timespec='seconds'), text, bool(dates or relatives or clocks)


def ground_request(question, payload, at, context=None):
    """Return checked response/context, or None for non-transit conversation.

Only complete, supported route grammar is authoritative. Ambiguous, negated or
multi-leg requests ask for clarification instead of trusting model assertions.
"""
    if payload.get('route') is not None:
        route = validate_form_route(payload['route'])
        # Form fields are authoritative, independent of both model text and
        # conversational history. Do not reparse a generated natural sentence.
        return _resolve_and_query((route['origin'], route['destination']), route.get('train_type'), at, at)
    text = unicodedata.normalize('NFKC', question).strip().rstrip('?!。.! ')
    if not re.search(r'A\d|車|站|航廈|班|幾點|機場|北車|高鐵|林口|長庚|普通|直達', text, re.I) and not payload.get('route') and not context:
        return None
    if re.search(r'抵達|到達|轉乘|換車|票價|票錢|多少錢|多久|多少分鐘|車程', text):
        return {'answer': '可以直接問起訖站的最近班次、首班或末班預定發車時間；目前尚未提供抵達時間、轉乘規劃及票價資料。'}
    modes = [mode for mode, pattern in BOUNDARY_PATTERNS.items() if re.search(pattern, text)]
    if len(modes) > 1 or '首末班' in text:
        return {'answer': '請先選擇要查首班還是末班，例如「A12到A18末班車幾點」。'}
    mode = modes[0] if modes else 'next'
    # A written date names the service day, even when the form clock is after
    # midnight. Otherwise retain the existing 03:00 operating-day boundary.
    explicit_date = bool(re.search(r'今天|明天|後天|昨天|(?<!\d)(?:\d{4}[-/年])?\d{1,2}[-/月]\d{1,2}(?:日|號)?(?!\d)', text))
    kinds = {kind for kind in TRAIN_CODES if kind in text}
    if len(kinds) > 1 or re.search(r'不要|不搭|不想|不是|別搭|除了|改去|先到|再到|順便|經由', text):
        return {'answer': '請確認這次的起站、目的站，以及要搭普通車或直達車。每次先查一段不需換車的旅程。'}
    kind = next(iter(kinds), None)
    try:
        query_time, route_text, explicit_time = _time_and_text(text, at)
    except ValueError as exc:
        message = str(exc)
        if not message.startswith(('請', '這')):
            message = '日期或時間無效，請重新確認，或在表單設定。'
        return {'answer': message}
    service_date = datetime.fromisoformat(query_time).date().isoformat() if explicit_date else None
    if modes:
        route_text = re.sub(r'(?:我)?(?:只|想要|想|要)?(?:搭乘|搭|坐)?(?:的)?(?:' + BOUNDARY_PATTERNS[mode] + ')', '', route_text)
    route_text = re.sub(r'(?:我)?(?:只|想|要|想要)?(?:搭乘|搭|坐)?(?:普通車|直達車)', '', route_text)
    route_text = re.sub(r'[,，]?\s*(?:的)?(?:下一班|最近一班)?(?:是)?(?:幾點|何時)(?:發車|出發)?(?:呢|嗎)?$', '', route_text).rstrip(' ,，')
    route_text = re.sub(r'[,，]?\s*(?:可以搭哪班車|可以嗎|呢)$', '', route_text).rstrip(' ,，')
    form_route = payload.get('route')
    slots = (form_route['origin'], form_route['destination']) if form_route else _parse_route(route_text)
    followup = bool(context and re.fullmatch(r'(?:那|那麼|改搭|換成|換|有)?\s*(?:下一班|最近兩班)?', route_text))
    if not slots and context and context.get('pending'):
        # Only a whole station answer can complete a pending clarification.
        slots = (route_text, context['destination']) if context['pending'] == 'origin' else (context['origin'], route_text)
        kind = kind or context.get('train_type')
        mode = mode if modes else context.get('query_mode', 'next')
        if not explicit_time and at == context.get('form_time'):
            query_time = context['query_time']
            service_date = context.get('service_date')
    elif not slots and followup and (kind or modes or explicit_time or '下一班' in route_text or '最近兩班' in route_text):
        slots = (context['origin'], context['destination'])
        kind = kind or context.get('train_type')
        if not modes and not re.search(r'下一班|最近兩班', route_text):
            mode = context.get('query_mode', 'next')
        if not explicit_time and at == context.get('form_time'):
            query_time = context['query_time']
            service_date = context.get('service_date')
    if not slots:
        return {'answer': CLARIFY}
    return _resolve_and_query(slots, kind, query_time, at, mode, service_date)


def _resolve_and_query(slots, kind, query_time, at, mode='next', service_date=None):
    values = list(slots)
    stations = json.loads(DEFAULT_CACHE.read_text(encoding='utf-8'))['stations']
    next_context = {'origin': values[0], 'destination': values[1], 'train_type': kind,
                    'query_time': query_time, 'form_time': at, 'query_mode': mode,
                    'service_date': service_date}
    for index, key in enumerate(('origin', 'destination')):
        try:
            values[index] = resolve_demo_station(values[index], stations)
            next_context[key] = values[index]
        except (StationClarificationRequired, ValueError) as exc:
            next_context['pending'] = key
            return {'answer': getattr(exc, 'question', CLARIFY),
                    'candidates': getattr(exc, 'candidates', []), 'context': next_context}
    result = (query_service_boundary(*values, query_time, mode, kind, service_date)
              if mode in BOUNDARY_PATTERNS else query_trains(*values, query_time, kind))
    call = {'name': 'get_service_boundary' if mode in BOUNDARY_PATTERNS else 'get_next_trains',
            'arguments': {'起站': values[0], '目的站': values[1], '查詢時間': query_time}}
    if mode in BOUNDARY_PATTERNS:
        call['arguments'].update(查詢類型=mode, 營運日=result['service_date'])
    if kind:
        call['arguments']['車種'] = kind
    return {'answer': render_grounded(result), 'result': result, 'call': call, 'context': next_context}
