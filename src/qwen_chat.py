"""Stateful local UI adapter for the actual saved Qwen LoRA model.

Qwen still runs on every request. Timetable claims are rendered from checked
data by an application guard; raw model output remains available for diagnosis.
"""

import json
import logging
import threading
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from src.bot_tools import SYSTEM_PROMPT, TOOL_SCHEMA
from src.model_inference import load_generator, run_turn
from src.timetable import TAIPEI
from src.timetable_guard import ground_request, validate_form_route, CLARIFY

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_ADAPTER = PROJECT / 'outputs/airport_mrt_adapter/adapter'


class ModelUnavailable(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class QwenChat:
    history_turn_limit = 3
    session_limit = 32

    def __init__(self, adapter=DEFAULT_ADAPTER, *, output_dir=None, loader=load_generator):
        self.adapter = Path(adapter).resolve()
        self.output_dir = Path(output_dir) if output_dir else None
        self.loader = loader
        self.generate = None
        self.status = 'not_started'
        self.error = None
        self.evidence = {}
        self.load_seconds = None
        self.lock = threading.Lock()
        self.sessions = OrderedDict()
        self.contexts = {}

    def start(self):
        if self.status != 'not_started':
            return
        self.status = 'loading'
        threading.Thread(target=self._load, name='qwen-loader', daemon=True).start()

    def _load(self):
        started = time.perf_counter()
        try:
            self.generate, self.evidence = self.loader(self.adapter)
            self.load_seconds = round(time.perf_counter() - started, 2)
            self.status = 'ready'
        except Exception as exc:
            logging.exception('Saved Qwen adapter failed to load')
            self.error = f'{type(exc).__name__}: {exc}'
            self.status = 'error'
        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            (self.output_dir / 'model_status.json').write_text(
                json.dumps(self.metadata(), ensure_ascii=False, indent=2), encoding='utf-8')

    def metadata(self):
        return {'engine': 'qwen', 'model_loaded': self.status == 'ready',
                'model_status': self.status, 'model_label': 'Qwen3 4B · 第二輪 LoRA',
                'model_error': self.error, 'load_seconds': self.load_seconds,
                'model_evidence': self.evidence, 'history_turn_limit': self.history_turn_limit,
                'reply_language': 'zh', 'response_policy': 'qwen_with_grounded_timetable',
                'train_type_filters': ['普通車', '直達車']}

    @staticmethod
    def _question(payload):
        # Preserve the model's input; the separate guard checks timetable facts.
        route = payload.get('route')
        if route is not None:
            validate_form_route(route)
            kind = f"只搭{route['train_type']}" if route.get('train_type') else '車種不限'
            return (f"查詢出發時間：{payload.get('at')}（臺灣時間）。"
                    f"我從 {route['origin']} 到 {route['destination']}，{kind}，請查最近兩班發車時間。")
        question = payload.get('message')
        if not isinstance(question, str) or not question.strip() or len(question) > 1000:
            raise ValueError('Message must contain 1 to 1000 characters')
        return question  # Preserve the user's exact wording.

    def chat(self, payload):
        if not isinstance(payload, dict):
            raise ValueError('Expected an object')
        question = self._question(payload)
        try:
            at = datetime.fromisoformat(payload.get('at'))
            if at.tzinfo is None:
                raise ValueError('Timezone required')
            at = at.astimezone(TAIPEI).isoformat(timespec='seconds')
        except (ValueError, TypeError) as exc:
            raise ValueError('Valid query time with timezone required') from exc
        requested_session = payload.get('session_id')
        if requested_session is not None and (not isinstance(requested_session, str) or len(requested_session) > 64):
            raise ValueError('Invalid conversation id')
        if self.status != 'ready':
            raise ModelUnavailable('model_not_ready', 'Qwen 尚未完成載入，請等待頁面顯示模型已就緒。')
        if not self.lock.acquire(blocking=False):
            raise ModelUnavailable('model_busy', 'Qwen 仍在處理上一個請求，請稍後再試。')
        started = time.perf_counter()
        try:
            is_reset = bool(requested_session and requested_session not in self.sessions)
            session_id = requested_session if requested_session in self.sessions else uuid4().hex
            turns = self.sessions.get(session_id, [])
            history = [message for turn in turns[-self.history_turn_limit:] for message in turn]
            messages = [{'role': 'system', 'content': SYSTEM_PROMPT + '\n目前臺灣時間：' + at}]
            messages += history + [{'role': 'user', 'content': question}]
            try:
                record = run_turn(self.generate, messages, [TOOL_SCHEMA])
            except ValueError as exc:
                if 'exceeds model context' in str(exc):
                    raise ModelUnavailable('context_limit', '對話已超過目前模型設定的長度，請點「新對話」再試。') from exc
                raise
            raw = record.get('final_output', record['first_output'])
            answer = raw.removesuffix('<|im_end|>').removesuffix('<|endoftext|>').strip()
            grounded = ground_request(question, payload, at, self.contexts.get(session_id))
            # Even an unexpected model-initiated timetable claim needs evidence.
            if grounded is None and (record.get('actual_call') or any(
                term in answer for term in ('普通車', '直達車', '發車', '班次', '轉乘'))):
                grounded = {'answer': CLARIFY}
            result = grounded.get('result') if grounded else None
            call = grounded.get('call') if grounded else None
            if grounded:
                answer = grounded['answer']
            elif record.get('tool_error'):
                answer = '這次模型未完成回答，請重新提問。查班次也可以使用旅程表單。'
            source = 'timetable' if result else 'clarification' if grounded else 'model'
            record['grounding'] = {'answer_source': source, 'actual_call': call, 'tool_result': result}
            response = {
                'engine': 'qwen', 'answer': {'zh': answer, 'en': answer},
                'session_id': session_id, 'conversation_reset': is_reset,
                'elapsed_seconds': round(time.perf_counter()-started, 2),
                'model_label': 'Qwen3 4B · 第二輪 LoRA',
                'tool_called': bool(result), 'actual_call': call,
                'model_tool_called': bool(record.get('tool_result')), 'answer_source': source,
                'tool_error': record.get('tool_error'),
                'raw_output': record, 'state': None,
            }
            if result:
                response['result'] = result
                response['confirmed_query'] = {
                    'origin': result['origin'], 'destination': result['destination'],
                    'at': result['query_time'], 'train_type': result.get('requested_train_type'),
                }
                if result.get('query_mode'):
                    response['confirmed_query'].update(query_mode=result['query_mode'], service_date=result['service_date'])
            response['candidates'] = grounded.get('candidates', []) if grounded else []
            if grounded or not record.get('tool_error'):
                turn = [{'role': 'user', 'content': question}]
                # Keep only the displayed answer; do not feed rejected assertions
                # or an application-only tool extension back as model history.
                turn.append({'role': 'assistant', 'content': answer})
                self.sessions[session_id] = (turns + [turn])[-self.history_turn_limit:]
                if grounded and grounded.get('context'):
                    self.contexts[session_id] = grounded['context']
                elif grounded:
                    self.contexts.pop(session_id, None)
                self.sessions.move_to_end(session_id)
                while len(self.sessions) > self.session_limit:
                    expired, _ = self.sessions.popitem(last=False)
                    self.contexts.pop(expired, None)
            if self.output_dir:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                with (self.output_dir / 'requests.jsonl').open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps({'recorded_at': datetime.now(TAIPEI).isoformat(),
                        'question': question, 'query_time': at,
                        'adapter_sha256': self.evidence.get('adapter_sha256'), **response}, ensure_ascii=False)+'\n')
            return response
        finally:
            self.lock.release()
