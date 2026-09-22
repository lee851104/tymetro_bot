"""Exercise the cloud queue/transport with a fake generator; no GPU claim."""

import os
import socket
import unittest
from pathlib import Path

os.environ['GRADIO_ANALYTICS_ENABLED'] = 'False'

import httpx
from gradio_client import Client

from src.hf_server import make_server
from src.qwen_chat import QwenChat

ROOT = Path(__file__).resolve().parents[1]


class SpaceTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seen = []

        def generate(messages, tools):
            cls.seen.append(messages)
            return '測試用模型輸出，非真實 GPU 推論'

        cls.service = QwenChat(loader=lambda _: (generate, {'test_only': True}))
        cls.service._load()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        cls.app = make_server(cls.service)
        cls.app.launch(server_name='127.0.0.1', server_port=port,
                       prevent_thread_lock=True, quiet=True, share=False,
                       run_history=False, mcp_server=False,
                       blocked_paths=[str(ROOT / 'data'), str(ROOT / 'outputs'), str(ROOT / 'config')])
        cls.url = f'http://127.0.0.1:{port}'
        cls.client = Client(cls.url, verbose=False)

    @classmethod
    def tearDownClass(cls):
        cls.app.get_blocks().close()

    def test_frontend_assets_and_private_files(self):
        with httpx.Client(base_url=self.url) as http:
            for path in ('/', '/app.js', '/style.css', '/favicon.svg', '/gradio-client.js'):
                self.assertEqual(http.get(path).status_code, 200, path)
            meta = http.get('/api/bootstrap').json()
            self.assertEqual(meta['transport'], 'gradio')
            self.assertEqual(len(meta['stations']), 22)
            self.assertIn('test_only', meta['model_evidence'])
            self.assertEqual(http.get('/data/station_aliases.json').status_code, 404)
            private = (ROOT / 'config/qwen3_instruct_chat_template.jinja').as_posix()
            self.assertNotEqual(http.get('/gradio_api/file=' + private).status_code, 200)

    def test_queue_form_and_conversation_keep_grounding(self):
        result = self.client.predict(payload={
            'route': {'origin': 'A1', 'destination': 'A13', 'train_type': '普通車'},
            'at': '2026-09-22T10:00:00+08:00'}, api_name='/chat')
        self.assertEqual([t['departure'][11:16] for t in result['result']['next_trains']], ['10:08', '10:23'])
        self.assertIn('測試用模型', result['raw_output']['first_output'])
        followup = self.client.predict(payload={
            'message': '那末班呢', 'session_id': result['session_id'],
            'at': '2026-09-22T10:00:00+08:00'}, api_name='/chat')
        self.assertEqual(followup['result']['query_mode'], 'last')
        self.assertEqual(followup['result']['origin'], 'A1')
        self.assertEqual(followup['session_id'], result['session_id'])
        self.assertGreater(len(self.seen[-1]), 2)

    def test_invalid_query_returns_readable_error(self):
        result = self.client.predict(payload={'message': 'A1到A13', 'at': 'invalid'}, api_name='/chat')
        self.assertEqual(result['error'], 'invalid_query')
        self.assertNotIn('result', result)


if __name__ == '__main__':
    unittest.main()
