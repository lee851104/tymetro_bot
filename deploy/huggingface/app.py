"""Hugging Face Gradio/ZeroGPU entrypoint (copied to the Space root)."""

import os
from pathlib import Path

import spaces  # CUDA emulation must be installed before model imports.

from src.hf_model import load_space_generator
from src.hf_server import make_server
from src.qwen_chat import QwenChat

root = Path(__file__).resolve().parent
service = QwenChat(root / 'adapter', loader=load_space_generator)
# Startup loading is synchronous for ZeroGPU's CUDA emulation lifecycle.
service._load()
if service.status != 'ready':
    raise RuntimeError('Trained Qwen LoRA failed to load; check Space logs')

app = make_server(service)
app.launch(server_name='0.0.0.0', server_port=int(os.environ.get('PORT', '7860')),
           show_error=False, run_history=False, mcp_server=False,
           blocked_paths=[str(root / 'adapter'), str(root / 'data'), str(root / 'config')])
