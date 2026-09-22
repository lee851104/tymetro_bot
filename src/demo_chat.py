"""Bilingual timetable demonstration. No LLM or training data is changed here."""

import json
import re
import unicodedata
from datetime import datetime

from src.bot_tools import get_next_trains, render_answer
from src.station_routes import StationClarificationRequired, normalize, resolve_station
from src.timetable import DEFAULT_CACHE, TAIPEI

# Official English station selector, checked 2026-09-22:
# https://www.tymetro.com.tw/tymetro-new/en/_pages/travel-guide/timetable-A7
ENGLISH_NAMES = dict(zip(
    ('A1 A2 A3 A4 A5 A6 A7 A8 A9 A10 A11 A12 A13 A14a A15 A16 A17 A18 A19 A20 A21 A22').split(),
    ('Taipei Main Station|Sanchong|New Taipei Industrial Park|Xinzhuang Fuduxin|Taishan|'
     'Taishan Guihe|National Taiwan Sport University|Chang Gung Memorial Hospital|Linkou|'
     'Shanbi|Kengkou|Airport Terminal 1|Airport Terminal 2|Airport Hotel|Dayuan|Hengshan|'
     'Linghang|Taoyuan HSR|Taoyuan Sports Park|Xingnan|Huanbei|Laojie River').split('|')))


def bootstrap():
    cache = json.loads(DEFAULT_CACHE.read_text(encoding='utf-8'))
    dates = sorted(cache['calendar'])
    return {
        'engine': 'timetable', 'model_loaded': False,
        'now': datetime.now(TAIPEI).isoformat(timespec='minutes'),
        'dates': dates, 'revision': cache.get('image_revision'),
        'stations': [{'code': code, 'zh': name, 'en': ENGLISH_NAMES[code]}
                     for code, name in cache['stations'].items()],
        'source': 'https://www.tymetro.com.tw/tymetro-new/tw/_pages/travel-guide/timetable.php',
    }


def resolve_demo_station(value, stations):
    """Whole-slot matching only. Never guess a station from a substring."""
    value = unicodedata.normalize('NFKC', value).strip()
    code = re.fullmatch(r'(?:station\s+)?(a\d+a?)\s*(?:站|station)?', value, re.I)
    if code:
        value = code[1]
    target = normalize(value)
    for code, name in ENGLISH_NAMES.items():
        if target in {normalize(name), normalize(name.removesuffix(' Station')), normalize(name + ' Station'),
                      normalize(code + ' ' + name), normalize(code + ' ' + name + ' Station')}:
            return code
    english_ambiguities = {'airport': '機場', 'taoyuanairport': '機場',
                          'downtown': '市區', 'citycenter': '市中心',
                          'xinzhuang': '新莊', 'baseballstadium': '棒球場'}
    return resolve_station(english_ambiguities.get(target, value), stations)


def answer_pair(zh, en, **extra):
    return {'answer': {'zh': zh, 'en': en}, 'engine': 'timetable', **extra}


def render_english(result):
    status = result['status']
    if status == 'ok':
        text = 'These scheduled trains stop at your destination without a transfer. '
        if result.get('remaining_departures') == 1:
            text += 'This is the last qualifying train of this service day. '
        if result.get('imminent_departures'):
            text += ('Another qualifying train leaves within 3 minutes. Consider the later '
                     'departures shown here; do not rush or run. ')
        return text + 'Arrival times and live service conditions are not available. Check station displays.'
    return {
        'only_imminent_departures_remaining': 'Only qualifying departures within 3 minutes remain. Do not rush or run. There are no later trains to this destination without a transfer this service day. Ask station staff about alternatives.',
        'no_direct_departures_remaining': 'No later trains reach this destination without a transfer this service day. Transfer options have not been calculated; this does not mean the entire line has stopped. Ask station staff about alternatives.',
        'same_station': 'Your origin and destination are the same. No train journey is needed.',
        'date_not_cached': 'No timetable is available here for this service date. Choose a date within the displayed coverage, or check the official timetable.',
        'outside_publication_horizon': 'This date is beyond the published timetable coverage. Check the official timetable.',
        'service_rules_unavailable': 'The stopping rules could not be verified. Please check with station staff.',
        'invalid_station': 'Please provide an Airport MRT station code or its full name.',
        'invalid_query_time': 'Please choose a valid date and time. All times use Taiwan time (UTC+8).',
        'station_needs_clarification': 'Please confirm the exact Airport MRT station.',
        'unavailable': 'The timetable is temporarily unavailable. Please check station displays or ask station staff.',
    }.get(status, 'The query could not be completed. Please check with station staff.')


def _parse_route(message):
    """Remove recognized question wrappers, then resolve both COMPLETE slots.

    This deliberately does not extract the first two station codes from arbitrary
    text: that would hide code/name conflicts, extra stops and negations.
    """
    value = unicodedata.normalize('NFKC', message).strip().rstrip('?!。.! ')
    prefixes = (
        r'^(?:請問(?:一下)?|麻煩(?:你)?|請(?:幫我)?(?:查(?:詢)?(?:一下)?)?|幫我查(?:詢)?|查詢)\s*',
        r'^(?:我(?:現在)?(?:想要|想|要)?(?:從|在)|從)\s*',
        r'^(?:please\s+|(?:can|could) you (?:please )?(?:tell me|show me|check|find)\s+)',
        r'^(?:(?:when|what time) is (?:the )?next train |(?:the )?next trains? |how long does it take (?:to go )?|how much (?:is (?:the )?fare |does it cost )?)?from\s+',
        r"^(?:I(?:'m| am) (?:at|going from)|I (?:want|would like) to (?:go |travel )?from)\s+",
    )
    for _ in range(4):
        previous = value
        for prefix in prefixes:
            value = re.sub(prefix, '', value, flags=re.I).lstrip(' ,')
        if value == previous:
            break
    value = re.sub(r'[,，]\s*(?:我)?(?:想要|想|要)?(?:到|去)', '到', value)
    value = re.sub(r'\s*我(?:想要|想|要)(?:到|去)', '到', value)
    value = re.sub(r"[,，]\s*(?:and )?I (?:want to go|am going) to\s+", ' to ', value, flags=re.I)
    # Suffixes describe intent, not part of the destination's name.
    suffix = (
        r'(?:的)?(?:下一班(?:車)?(?:是)?(?:幾點|何時|什麼時候)?(?:發車|出發|開車)?|'
        r'班次(?:時間)?|時刻表|怎麼(?:搭|坐|走)|如何搭(?:車)?|要怎麼(?:搭|坐)|'
        r'有(?:哪些|什麼)車|有車嗎|還有車嗎|幾點(?:有車|發車|出發)|'
        r'(?:要|需要)?多久|(?:要)?多少分鐘|車程(?:多久)?|票價(?:是)?多少(?:錢)?|(?:要)?多少錢)'
    )
    value = re.sub(r'[,，]?\s*' + suffix + r'(?:呢|嗎)?\s*$', '', value).rstrip(' ,，')
    reverse = re.fullmatch(
        r'(?:我)?(?:想要|想|要)?(?:到|去)\s*(.+?)\s*[,，;；]?\s*(?:我)?(?:目前)?(?:在|從)\s*(.+?)(?:出發)?',
        value, re.I)
    if reverse:
        return reverse[2].strip(), reverse[1].strip()
    reverse_en = re.fullmatch(
        r"(?:I (?:want|would like) to (?:go|travel) to|to)\s+(.+?)\s*,?\s+(?:I(?:'m| am) at|from)\s+(.+)",
        value, re.I)
    if reverse_en:
        return reverse_en[2].strip(), reverse_en[1].strip()
    match = re.fullmatch(r'(.+?)\s*(?:要到|想到|到|至|要去|去|→|->|[-–—~]|\s+to\s+)\s*(.+)', value, re.I)
    return tuple(part.strip() for part in match.groups()) if match else None


def _unsupported_intent(message):
    """Keep a fare/duration question distinct from a failed station match."""
    intents = []
    if re.search(r'票價|票錢|多少錢|\bfare\b|how much|ticket.*cost', message, re.I):
        intents.append('fare')
    if re.search(r'多久|多少分鐘|車程|需時|how long|travel time|journey time', message, re.I):
        intents.append('duration')
    return intents


def _capability_reply(intents, stations=None, values=None):
    prefix_zh = prefix_en = ''
    if values:
        origin, destination = values
        prefix_zh = f'已辨識你要從 {origin} {stations[origin]} 到 {destination} {stations[destination]}。'
        prefix_en = f'Your route is {origin} {ENGLISH_NAMES[origin]} to {destination} {ENGLISH_NAMES[destination]}. '
    zh, en = [], []
    if 'fare' in intents:
        zh.append('目前尚未接上票價資料，無法提供可靠票價。')
        en.append('Fare data has not been connected, so I cannot provide a verified price.')
    if 'duration' in intents:
        zh.append('目前只有發車班表，尚未提供車程或抵達時間，不能用下一班的等待時間當成車程。')
        en.append('Only departure timetables are available. Journey duration and arrival times are not available; waiting time is not travel time.')
    return answer_pair(prefix_zh + ''.join(zh) + '可先用旅程表單查發車班次，其他資訊請查官方資料。',
                       prefix_en + ' '.join(en) + ' Use the journey form to check departures, or consult official information for these details.',
                       unsupported_intents=intents)


def chat(payload):
    if not isinstance(payload, dict):
        raise ValueError('Expected an object')
    message = payload.get('message', '')
    if not isinstance(message, str) or len(message) > 1000:
        raise ValueError('Message must contain at most 1000 characters')
    message = unicodedata.normalize('NFKC', message).strip()
    intents = []
    time_source = 'form'
    at = payload.get('at')
    try:
        parsed_at = datetime.fromisoformat(at)
        if parsed_at.tzinfo is None:
            raise ValueError('Timezone is required')
        at = parsed_at.astimezone(TAIPEI).isoformat(timespec='seconds')
    except (ValueError, TypeError):
        return answer_pair('請先選擇有效的日期與時間（臺灣時間）。', render_english({'status': 'invalid_query_time'}))

    slots = None
    if payload.get('route') is not None:
        route = payload['route']
        if not isinstance(route, dict):
            raise ValueError('Invalid route')
        slots = (route.get('origin'), route.get('destination'))
    elif message.strip().lower() in {'末班提醒', 'last train advice'}:
        return answer_pair('如果班次在 3 分鐘內發車，建議考慮較晚班次，避免趕車或奔跑。若只剩末班，我會明確告知沒有更晚的不換車班次。請提供起訖站，並設定要查詢的日期與時間。',
                           'For departures within 3 minutes, consider a later train and avoid rushing. If only the last train remains, I will say when no later journey without a transfer is available. Choose your route, date and time to check.')
    else:
        intents = _unsupported_intent(message)
        # Never silently ignore dates, times or journey constraints typed in chat.
        if re.search(r'\d{1,2}[:：]\d{2}|\d{1,2}\s*(?:點|時)|明天|後天|昨天|今天|tomorrow|today|yesterday|\d{4}[-/]\d|\d{1,2}\s*(?:am|pm)\b|抵達|到達|arriv|最早|最晚|first train|last train|末班|首班|直達車|普通車|express|commuter', message, re.I):
            return answer_pair('請用左側／上方表單設定日期與時間，再查起訖站。目前展示版查詢的是該時間之後、不需換車的最近兩班；尚不支援指定車種、抵達時間或直接搜尋首末班。',
                               'Set the date and time in the journey form, then choose your stations. This demo finds the next two departures that require no transfer. Train-type filters, arrival-time planning and direct first/last-train searches are not supported.')
        if re.search(r'現在|\b(?:right )?now\b', message, re.I):
            at = datetime.now(TAIPEI).isoformat(timespec='seconds')
            time_source = 'current'
            message = re.sub(r'現在|\b(?:right )?now\b', '', message, flags=re.I).strip()
        slots = _parse_route(message)
        state = payload.get('state')
        if slots is None and isinstance(state, dict) and state.get('pending') in {'origin', 'destination'}:
            origin, destination = state.get('origin'), state.get('destination')
            slots = (message.strip(), destination) if state['pending'] == 'origin' else (origin, message.strip())
        if slots is None:
            if intents:
                return _capability_reply(intents)
            return answer_pair('告訴我起站與目的站，例如「北車到二航」或「A7 到 A12」，也可以直接使用旅程表單。日期與時間以表單設定為準。目前可查預定班次；票價、轉乘與即時狀態請查官方資訊。',
                               'Tell me your route, for example “Taipei Main Station to Terminal 2” or “A7 to A12”, or use the journey form. Queries use the date and time in the form. I can check scheduled departures; use official information for fares, transfers and live service.')
    if not all(isinstance(s, str) and 0 < len(s.strip()) <= 120 for s in slots):
        raise ValueError('Please provide two station names')
    stations = json.loads(DEFAULT_CACHE.read_text(encoding='utf-8'))['stations']
    values = list(slots)
    for index, slot in enumerate(('origin', 'destination')):
        try:
            values[index] = resolve_demo_station(values[index], stations)
        except (StationClarificationRequired, ValueError) as exc:
            candidates = getattr(exc, 'candidates', [])
            zh = getattr(exc, 'question', '無法辨識這個站名，請提供機捷站碼或完整站名。')
            return answer_pair(zh, f'Please confirm the exact station for “{values[index]}”. Use a station code or select a station below.',
                               candidates=candidates,
                               state={'origin': values[0], 'destination': values[1], 'pending': slot})
    if intents:
        return _capability_reply(intents, stations, values)
    result = get_next_trains(*values, at)
    return answer_pair(render_answer(result), render_english(result), result=result, state=None, time_source=time_source)
