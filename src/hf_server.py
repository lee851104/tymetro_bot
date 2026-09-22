"""Serve the existing custom frontend through Gradio's ZeroGPU-aware queue."""

import json
import logging
from pathlib import Path

from fastapi.responses import FileResponse, JSONResponse
from gradio import Server

from src.demo_chat import bootstrap
from src.qwen_chat import ModelUnavailable

ROOT = Path(__file__).resolve().parents[1]


def make_server(service):
    app = Server(title='下一站｜機場捷運 AI 查班助手', docs_url=None, redoc_url=None)

    @app.middleware('http')
    async def response_headers(request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        if request.url.path in ('/', '/api/bootstrap'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    # Only named frontend files are served; adapter/data are never static mounts.
    assets = {
        '/': (ROOT / 'web/index.html', 'text/html'),
        '/app.js': (ROOT / 'web/app.js', 'application/javascript'),
        '/style.css': (ROOT / 'web/style.css', 'text/css'),
        '/favicon.svg': (ROOT / 'web/favicon.svg', 'image/svg+xml'),
        '/gradio-client.js': (ROOT / 'deploy/huggingface/vendor/gradio-client.js', 'application/javascript'),
    }

    def serve_asset(path, media_type):
        def endpoint():
            return FileResponse(path, media_type=media_type)
        return endpoint

    for url, (path, media_type) in assets.items():
        app.add_api_route(url, serve_asset(path, media_type), methods=['GET'], include_in_schema=False)

    @app.get('/api/bootstrap')
    def metadata():
        data = bootstrap()
        data.update(service.metadata())
        data.update(transport='gradio', deployment='huggingface-zerogpu')
        data['model_error'] = '雲端模型載入失敗，請稍後再試。' if service.error else None
        return JSONResponse(data)

    @app.api(name='chat', concurrency_limit=1, time_limit=240,
             description='使用已訓練 Qwen LoRA 和核對過的時刻表查詢機捷班次')
    def chat(payload: dict) -> dict:
        try:
            if len(json.dumps(payload, ensure_ascii=False).encode('utf-8')) > 16384:
                raise ValueError('Request too large')
            return service.chat(payload)
        except ModelUnavailable as exc:
            return {'error': exc.code, 'message': str(exc)}
        except (ValueError, TypeError, UnicodeDecodeError):
            return {'error': 'invalid_query', 'message': '查詢格式不正確，請確認起訖站與日期時間。'}
        except Exception:
            logging.exception('Space query failed')
            return {'error': 'query_failed', 'message': '雲端查詢未完成，可能是 GPU 額度或排隊狀態；請稍後重試。'}

    return app
