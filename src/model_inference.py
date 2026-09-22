"""One inference and tool-execution path for local use and evaluation."""

import hashlib
import json
import re
from pathlib import Path

from src.bot_tools import dispatch_tool

CONTEXT_LENGTH = 2048
GENERATION_CONFIG = {"do_sample": False, "max_new_tokens": 256, "use_cache": True}


def parse_call(text):
    matches = re.findall(r"<tool_call>\s*(.*?)\s*</tool_call>", text, re.S)
    if not matches and "<tool_call>" not in text and "</tool_call>" not in text:
        return None
    if len(matches) != 1 or text.count("<tool_call>") != 1 or text.count("</tool_call>") != 1:
        raise ValueError("expected one complete tool call")
    call = json.loads(matches[0])
    if not isinstance(call, dict) or set(call) != {"name", "arguments"}:
        raise ValueError("invalid tool call object")
    if isinstance(call.get("arguments"), str):
        call["arguments"] = json.loads(call["arguments"])
    return call


def decode_completion(tokenizer, output_ids, prompt_length):
    """Slice token positions, never split text on the word 'assistant'."""
    return tokenizer.decode(output_ids[prompt_length:], skip_special_tokens=False)


def run_turn(generate, messages, tools):
    """Run at most one tool call, preserving raw model output for review."""
    text = generate(messages, tools)
    record = {"first_output": text, "actual_call": None}
    try:
        call = parse_call(text)
        record["actual_call"] = call
        if call:
            result = dispatch_tool(call["name"], call["arguments"])
            followup = messages + [
                {"role": "assistant", "tool_calls": [{"type": "function", "function": call}]},
                {"role": "tool", "name": call["name"], "content": json.dumps(result, ensure_ascii=False)},
            ]
            record["tool_result"] = result
            record["final_output"] = generate(followup, tools)
            if parse_call(record["final_output"]) is not None:
                raise ValueError("unexpected repeated tool call instead of final answer")
    except (ValueError, KeyError, TypeError) as exc:
        record["tool_error"] = str(exc)
    return record


def calls_equivalent(actual, expected):
    """Accept supported aliases with identical tool outcomes, without relaxing exact metrics."""
    if actual == expected:
        return True
    if actual is None or expected is None:
        return False
    try:
        a = dispatch_tool(actual["name"], actual["arguments"])
        b = dispatch_tool(expected["name"], expected["arguments"])
    except (ValueError, KeyError, TypeError):
        return False
    if a["status"] in {"unavailable", "invalid_station", "invalid_query_time"}:
        return False
    return a == b


def load_generator(adapter=None):
    from unsloth import FastLanguageModel
    import torch
    from scripts.train_lora import MODEL_ID, CHAT_TEMPLATE

    torch.manual_seed(42)
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=str(Path(adapter).resolve()) if adapter else MODEL_ID,
        max_seq_length=CONTEXT_LENGTH, load_in_4bit=True, dtype=None)
    FastLanguageModel.for_inference(model)
    tokenizer.chat_template = CHAT_TEMPLATE.read_text(encoding="utf-8")
    evidence = {"requested_adapter": str(adapter) if adapter else None,
                "base_model": MODEL_ID,
                "base_revision": getattr(model.config, "_commit_hash", None),
                "template_sha256": hashlib.sha256(CHAT_TEMPLATE.read_bytes()).hexdigest(),
                "shared_inference_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "context_length": CONTEXT_LENGTH, "generation": GENERATION_CONFIG}
    if adapter:
        weights = [(name, p) for name, p in model.named_parameters() if "lora_B" in name]
        if not getattr(model, "peft_config", None) or not weights:
            raise ValueError("requested adapter was not loaded")
        if not all(torch.isfinite(p).all().item() for _, p in weights):
            raise ValueError("adapter contains non-finite weights")
        magnitude = sum(p.detach().float().abs().sum().item() for _, p in weights)
        if magnitude == 0:
            raise ValueError("adapter LoRA B weights are all zero")
        evidence.update(adapter_sha256=hashlib.sha256(
            (Path(adapter) / "adapter_model.safetensors").read_bytes()).hexdigest(),
            lora_B_tensor_count=len(weights), lora_B_absolute_sum=magnitude)

    def generate(messages, tools):
        inputs = tokenizer.apply_chat_template(messages, tools=tools, tokenize=True,
                    add_generation_prompt=True, return_tensors="pt", return_dict=True).to("cuda")
        prompt_length = inputs["input_ids"].shape[1]
        if prompt_length + GENERATION_CONFIG["max_new_tokens"] > CONTEXT_LENGTH:
            raise ValueError("evaluation prompt plus generation exceeds model context")
        with torch.inference_mode():
            output = model.generate(**inputs, **GENERATION_CONFIG,
                                    pad_token_id=tokenizer.pad_token_id)
        return decode_completion(tokenizer, output[0], prompt_length)

    return generate, evidence
