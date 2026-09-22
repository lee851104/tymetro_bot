"""Service-contract tests; actual GPU inference is verified separately."""

import json
import threading
import unittest
from urllib.request import Request, urlopen

from scripts.serve_demo import DemoServer, Handler
from src.qwen_chat import ModelUnavailable, QwenChat

AT = '2026-09-22T20:30:00+08:00'


def make_service(generate):
    service = QwenChat(loader=lambda adapter: (generate, {'adapter_sha256': 'test-only'}))
    service._load()
    return service


class QwenChatTests(unittest.TestCase):
    def test_exact_user_text_reaches_qwen_but_unqueried_denial_is_not_displayed(self):
        seen = []
        def generate(messages, tools):
            seen.append(messages)
            return 'A1 到 A13 沒有普通車，請確認目的站。<|im_end|>'
        service = make_service(generate)
        question = 'A1到A13我要搭普通車是幾點'
        result = service.chat({'message': question, 'at': AT})
        self.assertEqual(seen[0][-1]['content'], question)
        self.assertEqual(result['engine'], 'qwen')
        self.assertNotIn('沒有普通車', result['answer']['zh'])
        self.assertTrue(result['tool_called'])
        self.assertFalse(result['model_tool_called'])
        self.assertEqual(result['answer_source'], 'timetable')
        self.assertEqual([r['departure'][11:16] for r in result['result']['next_trains']], ['20:38','20:53'])
        self.assertTrue(all(r['train_type'] == '普通車' for r in result['result']['next_trains']))
        self.assertIn('沒有普通車', result['raw_output']['first_output'])
        self.assertNotIn('沒有普通車', service.sessions[result['session_id']][-1][-1]['content'])

    def test_grounding_rejects_incorrect_terminal_transfer_claims(self):
        call = {'name': 'get_next_trains', 'arguments': {'起站': 'A1', '目的站': 'A9', '查詢時間': AT}}
        def generate(messages, tools):
            if messages[-1]['role'] == 'tool':
                return '請在 A22 轉乘。<|im_end|>'
            return '<tool_call>' + json.dumps(call) + '</tool_call>'
        service = make_service(generate)
        result = service.chat({'message': '我要去A9我在A1', 'at': AT})
        self.assertNotIn('轉乘', result['answer']['zh'])
        self.assertIn('都會停靠 A9', result['answer']['zh'])
        self.assertEqual(result['result']['destination'], 'A9')
        self.assertTrue(result['tool_called'])
        self.assertEqual(result['actual_call'], call)
        self.assertIn('final_output', result['raw_output'])
        self.assertIn('轉乘', result['raw_output']['final_output'])

    def test_followup_history_and_new_session_are_separate(self):
        seen = []
        def generate(messages, tools):
            seen.append(messages)
            return '你要到第一航廈還是第二航廈？'
        service = make_service(generate)
        first = service.chat({'message':'我在A1，要去機場', 'at':AT})
        service.chat({'message':'第一航廈', 'at':AT, 'session_id':first['session_id']})
        self.assertEqual([m['role'] for m in seen[-1]], ['system','user','assistant','user'])
        self.assertEqual(seen[-1][1]['content'], '我在A1，要去機場')
        service.chat({'message':'另一個問題', 'at':AT})
        self.assertEqual(len(seen[-1]), 2)

    def test_form_also_goes_through_qwen(self):
        seen = []
        service = make_service(lambda messages, tools: seen.append(messages[-1]['content']) or '模型回覆')
        result = service.chat({'route':{'origin':'A1','destination':'A9'}, 'at':AT})
        self.assertEqual(seen, [f'查詢出發時間：{AT}（臺灣時間）。我從 A1 到 A9，車種不限，請查最近兩班發車時間。'])
        self.assertEqual(result['answer_source'], 'timetable')
        self.assertEqual(result['result']['destination'], 'A9')

    def test_visual_picker_fields_reach_model_and_override_incorrect_model_call(self):
        seen = []
        wrong = {'name':'get_next_trains','arguments':{'起站':'A18','目的站':'A1','查詢時間':AT}}
        def generate(messages, tools):
            seen.append(messages)
            return 'A13 沒有普通車' if messages[-1]['role']=='tool' else '<tool_call>'+json.dumps(wrong)+'</tool_call>'
        service = make_service(generate)
        at='2026-09-22T10:00:00+08:00'
        result=service.chat({'route':{'origin':'A1','destination':'A13','train_type':'普通車'},'at':at})
        prompt=seen[0][-1]['content']
        self.assertIn('從 A1 到 A13',prompt)
        self.assertIn('只搭普通車',prompt)
        self.assertIn(at,prompt)
        self.assertEqual(result['confirmed_query'],{'origin':'A1','destination':'A13','train_type':'普通車','at':at})
        self.assertEqual([t['departure'][11:16] for t in result['result']['next_trains']],['10:08','10:23'])
        self.assertEqual(result['raw_output']['actual_call'],wrong)
        self.assertNotIn('沒有普通車',result['answer']['zh'])

    def test_selected_form_does_not_inherit_previous_time_route_or_type(self):
        service=make_service(lambda *_:'沒有車')
        first=service.chat({'message':'我9/22早上10點要從A1到A12可以搭哪班車','at':AT})
        request={'route':{'origin':'A13','destination':'A1','train_type':'直達車'},'at':AT,'session_id':first['session_id']}
        second=service.chat(request)
        self.assertEqual(second['confirmed_query'],{'origin':'A13','destination':'A1','train_type':'直達車','at':AT})
        self.assertEqual(second['result']['status'],'ok')
        self.assertTrue(all('直達車' in t['train_type'] for t in second['result']['next_trains']))

    def test_picker_invalid_codes_and_types_rejected_before_model_inference(self):
        def never(*args):
            self.fail('invalid form must not reach model')
        service=make_service(never)
        for route in ({'origin':'A23','destination':'A1'}, {'origin':'A1','destination':'A13','train_type':'高鐵'},
                      {'origin':'台北','destination':'A13'}, {'origin':'A1','destination':'A13','train_type':['普通車']}):
            with self.subTest(route=route), self.assertRaises(ValueError):
                service.chat({'route':route,'at':AT})

    def test_model_not_loaded_or_busy_never_falls_back_to_parser(self):
        service = QwenChat()
        with self.assertRaises(ModelUnavailable) as error:
            service.chat({'message':'A1到A9', 'at':AT})
        self.assertEqual(error.exception.code, 'model_not_ready')
        service = make_service(lambda *_:'test')
        service.lock.acquire()
        try:
            with self.assertRaises(ModelUnavailable) as error:
                service.chat({'message':'A1到A9', 'at':AT})
            self.assertEqual(error.exception.code, 'model_busy')
        finally:
            service.lock.release()

    def test_context_limit_is_reported_and_releases_gpu_lock(self):
        def generate(*args):
            raise ValueError('evaluation prompt plus generation exceeds model context')
        service = make_service(generate)
        with self.assertRaises(ModelUnavailable) as error:
            service.chat({'message':'A1到A9', 'at':AT})
        self.assertEqual(error.exception.code, 'context_limit')
        self.assertFalse(service.lock.locked())

    def test_bad_model_tool_call_is_diagnostic_but_grounded_query_still_works(self):
        service = make_service(lambda *_:'<tool_call>')
        result = service.chat({'message':'A1到A9', 'at':AT})
        self.assertTrue(result['tool_error'])
        self.assertTrue(result['tool_called'])
        self.assertEqual(result['raw_output']['first_output'], '<tool_call>')
        self.assertIn(result['session_id'], service.sessions)
        self.assertEqual(result['answer_source'], 'timetable')

    def test_http_routes_to_model_and_reports_model_evidence(self):
        server = DemoServer(('127.0.0.1', 0), Handler)
        server.model_service = make_service(lambda *_:'實際經過 generator')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base+'/api/bootstrap') as response:
                data=json.load(response)
                self.assertEqual(data['engine'],'qwen')
                self.assertTrue(data['model_loaded'])
                self.assertEqual(data['model_evidence']['adapter_sha256'],'test-only')
            request=Request(base+'/api/chat', data=json.dumps({'message':'你好','at':AT}).encode(), headers={'Content-Type':'application/json'})
            with urlopen(request) as response:
                self.assertEqual(json.load(response)['answer']['zh'],'實際經過 generator')
            with self.assertRaises(OSError):
                DemoServer(('127.0.0.1',server.server_port),Handler)
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_wrong_model_time_cannot_override_current_form_or_typed_time(self):
        call = {'name': 'get_next_trains', 'arguments': {'起站': 'A1', '目的站': 'A13', '查詢時間': '2026-09-22T20-30+08:00'}}
        service = make_service(lambda messages, _: '沒有普通車' if messages[-1]['role'] == 'tool' else '<tool_call>'+json.dumps(call)+'</tool_call>')
        result = service.chat({'message': 'A1到A13我要搭普通車是幾點', 'at': AT})
        self.assertEqual(result['result']['query_time'], AT)
        self.assertEqual(result['raw_output']['tool_result']['status'], 'invalid_query_time')
        first = service.chat({'message':'我9/22早上10點要從A1到A12可以搭哪班車','at':AT})
        second = service.chat({'message':'那普通車呢','at':AT,'session_id':first['session_id']})
        self.assertEqual(second['result']['query_time'], '2026-09-22T10:00:00+08:00')
        self.assertEqual(second['result']['destination'], 'A12')

    def test_failed_route_parse_never_displays_model_denial(self):
        service = make_service(lambda *_:'這裡沒有普通車。')
        result = service.chat({'message':'我要搭普通車去機場','at':AT})
        self.assertEqual(result['answer_source'], 'clarification')
        self.assertNotIn('這裡沒有普通車', result['answer']['zh'])
        self.assertFalse(result['tool_called'])


if __name__ == '__main__':
    unittest.main()
