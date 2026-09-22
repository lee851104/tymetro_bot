"""Run the local bilingual timetable UI: python -m scripts.serve_demo."""

import argparse
import json
import logging
import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from src.demo_chat import bootstrap, chat
from src.qwen_chat import DEFAULT_ADAPTER, ModelUnavailable, QwenChat

ROOT = Path(__file__).resolve().parents[1] / 'web'
ASSETS = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
          '/style.css': ('style.css', 'text/css; charset=utf-8'),
          '/favicon.svg': ('favicon.svg', 'image/svg+xml')}


class Handler(BaseHTTPRequestHandler):
    def send_bytes(self, status, body, content_type):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def json(self, status, value):
        self.send_bytes(status, json.dumps(value, ensure_ascii=False).encode(), 'application/json; charset=utf-8')

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/api/bootstrap':
            try:
                data = bootstrap()
                service = getattr(self.server, 'model_service', None)
                if service:
                    data.update(service.metadata())
                self.json(200, data)
            except (OSError, ValueError, KeyError):
                self.json(503, {'error': 'Timetable unavailable'})
        elif path in ASSETS:
            name, kind = ASSETS[path]
            self.send_bytes(200, (ROOT / name).read_bytes(), kind)
        else:
            self.json(404, {'error': 'Not found'})

    def do_POST(self):
        if urlsplit(self.path).path != '/api/chat':
            return self.json(404, {'error': 'Not found'})
        # No cross-origin API access; bind loopback only, with a small request cap.
        origin = self.headers.get('Origin')
        allowed = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
        if origin and origin not in allowed:
            return self.json(403, {'error': 'Origin not allowed'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 16384:
                return self.json(413, {'error': 'Request too large or empty'})
            payload = json.loads(self.rfile.read(size))
            service = getattr(self.server, 'model_service', None)
            self.json(200, service.chat(payload) if service else chat(payload))
        except ModelUnavailable as exc:
            self.json(409 if exc.code == 'model_busy' else 503,
                      {'error': exc.code, 'message': str(exc), 'engine': 'qwen'})
        except (ValueError, TypeError, UnicodeDecodeError):
            self.json(400, {'error': 'Invalid query'})
        except Exception:
            logging.exception('Demo query failed')
            self.json(503, {'error': 'query_failed', 'message': '查詢未完成，請查看服務紀錄後再試；未改用固定回覆。'})


class DemoServer(ThreadingHTTPServer):
    # Windows SO_REUSEADDR can allow two different model versions on one port.
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--engine', choices=('qwen', 'timetable'), default='qwen')
    parser.add_argument('--adapter', type=Path, default=DEFAULT_ADAPTER)
    args = parser.parse_args()
    server = DemoServer(('127.0.0.1', args.port), Handler)
    server.model_service = None
    if args.engine == 'qwen':
        project = ROOT.parent
        os.environ['HF_HOME'] = str(project / 'models/huggingface')
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'
        server.model_service = QwenChat(args.adapter, output_dir=project / 'outputs/demo/qwen')
        server.model_service.start()
    print(f'Airport MRT demo: http://127.0.0.1:{args.port}', flush=True)
    print(f'Engine: {args.engine}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
