"""Prepare an allowlisted, traceable Space upload folder; never copy credentials."""

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / 'outputs/huggingface_space'
FILES = [
    'src/__init__.py', 'src/bot_tools.py', 'src/demo_chat.py', 'src/model_inference.py',
    'src/qwen_chat.py', 'src/station_routes.py', 'src/timetable.py',
    'src/timetable_guard.py', 'src/service_calendar.py', 'src/hf_model.py', 'src/hf_server.py',
    'config/qwen3_instruct_chat_template.jinja',
    'data/station_aliases.json', 'data/timetable/cache.json',
    'data/timetable/calendar_2026.json', 'data/timetable/service_rules.json',
    'web/index.html', 'web/app.js', 'web/style.css', 'web/favicon.svg',
    'deploy/huggingface/vendor/gradio-client.js',
    'deploy/huggingface/vendor/gradio-client.LICENSE',
]
ADAPTER_FILES = ['adapter_config.json', 'adapter_model.safetensors',
                 'tokenizer.json', 'tokenizer_config.json', 'chat_template.jinja']


def prepare(destination=DESTINATION):
    destination = Path(destination)
    mapping = {name: ROOT / name for name in FILES}
    mapping.update({name: ROOT / 'deploy/huggingface' / name
                    for name in ('app.py', 'README.md', 'requirements.txt')})
    mapping.update({'adapter/' + name: ROOT / 'outputs/airport_mrt_adapter/adapter' / name
                    for name in ADAPTER_FILES})
    # Reject stale or unexpected files instead of silently uploading them.
    if destination.exists():
        unexpected = {p.relative_to(destination).as_posix() for p in destination.rglob('*') if p.is_file()} - set(mapping) - {'deployment_manifest.json'}
        if unexpected:
            raise ValueError(f'Unexpected upload files: {sorted(unexpected)}')
    manifest = {'adapter': 'Second QLoRA round / original trained weights', 'files': []}
    for relative, source in mapping.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        content = target.read_bytes()
        manifest['files'].append({'path': relative, 'bytes': len(content),
                                  'sha256': hashlib.sha256(content).hexdigest()})
    (destination / 'deployment_manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'folder': str(destination), 'files': len(mapping) + 1,
                      'total_bytes': sum(item['bytes'] for item in manifest['files'])}))
    return manifest


if __name__ == '__main__':
    prepare()
