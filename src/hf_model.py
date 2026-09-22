"""Transformers/PEFT inference for ZeroGPU; uses the saved Round 2 adapter."""

import hashlib
from pathlib import Path

from src.model_inference import CONTEXT_LENGTH, GENERATION_CONFIG, decode_completion

BASE_MODEL = 'Qwen/Qwen3-4B-Instruct-2507'
BASE_REVISION = 'cdbee75f17c01a7cc42f958dc650907174af0554'
TRAINING_BASE = 'unsloth/Qwen3-4B-Instruct-2507-bnb-4bit'
ROOT = Path(__file__).resolve().parents[1]


def load_space_generator(adapter):
    # spaces must patch CUDA before torch/transformers are imported.
    import spaces
    import torch
    from peft import PeftModel
    from safetensors import safe_open
    from transformers import AutoModelForCausalLM, AutoTokenizer

    adapter = Path(adapter)
    weights_path = adapter / 'adapter_model.safetensors'
    # Check weights on CPU: scalar CUDA reads cannot run outside @spaces.GPU.
    with safe_open(weights_path, framework='pt', device='cpu') as weights:
        keys = [key for key in weights.keys() if 'lora_B' in key]
        if not keys:
            raise ValueError('Adapter has no LoRA B weights')
        magnitude = 0.0
        for key in keys:
            tensor = weights.get_tensor(key)
            if not torch.isfinite(tensor).all().item():
                raise ValueError('Adapter contains non-finite weights')
            magnitude += tensor.float().abs().sum().item()
        if magnitude == 0:
            raise ValueError('Adapter weights are all zero')

    tokenizer = AutoTokenizer.from_pretrained(str(adapter), local_files_only=True)
    tokenizer.chat_template = (ROOT / 'config/qwen3_instruct_chat_template.jinja').read_text(encoding='utf-8')
    # BF16 fits ZeroGPU and avoids Unsloth/bitsandbytes CUDA compilation.
    # The adapter is unchanged; raw outputs can differ from local 4-bit inference.
    base = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL, revision=BASE_REVISION, dtype=torch.bfloat16,
        device_map='cuda', attn_implementation='sdpa', trust_remote_code=False)
    model = PeftModel.from_pretrained(base, str(adapter), is_trainable=False)
    model.eval()
    if not model.peft_config:
        raise ValueError('Trained adapter did not load')

    @spaces.GPU(duration=60)
    def generate(messages, tools):
        torch.manual_seed(42)
        inputs = tokenizer.apply_chat_template(
            messages, tools=tools, tokenize=True, add_generation_prompt=True,
            return_tensors='pt', return_dict=True).to('cuda')
        prompt_length = inputs['input_ids'].shape[1]
        if prompt_length + GENERATION_CONFIG['max_new_tokens'] > CONTEXT_LENGTH:
            raise ValueError('evaluation prompt plus generation exceeds model context')
        with torch.inference_mode():
            output = model.generate(**inputs, **GENERATION_CONFIG,
                                    pad_token_id=tokenizer.pad_token_id)
        return decode_completion(tokenizer, output[0], prompt_length)

    evidence = {
        'base_model': BASE_MODEL, 'base_revision': BASE_REVISION,
        'training_base_model': TRAINING_BASE, 'inference_precision': 'bfloat16',
        'adapter_sha256': hashlib.sha256(weights_path.read_bytes()).hexdigest(),
        'lora_B_tensor_count': len(keys), 'lora_B_absolute_sum': magnitude,
        'context_length': CONTEXT_LENGTH, 'generation': GENERATION_CONFIG,
        'runtime': 'Hugging Face ZeroGPU / Transformers + PEFT',
    }
    return generate, evidence
