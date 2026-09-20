"""QLoRA entry point for the later RTX 4060 Linux/WSL2 machine.

No GPU libraries are imported by ``--check``. Always run smoke, reload,
then train; a data change invalidates the smoke marker.
"""

import argparse
import hashlib
import json
import platform
from pathlib import Path

from scripts.validate_data import load_jsonl, validate_outputs


ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "unsloth/Qwen3-4B-Instruct-2507-bnb-4bit"
MAX_LENGTH = 1024


def dataset_digest(root=ROOT):
    digest = hashlib.sha256()
    for name in ("train.jsonl", "val.jsonl"):
        digest.update((Path(root) / "data" / "processed" / name).read_bytes())
    return digest.hexdigest()


def check_training_gate(root, digest):
    marker = Path(root) / "outputs" / "smoke" / "status.json"
    if not marker.exists():
        return ["smoke run and adapter reload are required first"]
    try:
        status = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["smoke status is unreadable"]
    if status.get("dataset_sha256") != digest:
        return ["training data changed after smoke run"]
    if not status.get("adapter_reloaded"):
        return ["reload the smoke adapter before full training"]
    return []


def _assert_gpu(torch):
    if not torch.cuda.is_available():
        raise SystemExit("CUDA GPU unavailable; train on the RTX 4060 machine")
    properties = torch.cuda.get_device_properties(0)
    if properties.total_memory < 7.3 * 1024**3:
        raise SystemExit(f"GPU {properties.name} has less than 8 GB-class VRAM")
    return properties.name


def _load_model():
    from unsloth import FastLanguageModel

    return FastLanguageModel.from_pretrained(
        model_name=MODEL_ID,
        max_seq_length=MAX_LENGTH,
        dtype=None,
        load_in_4bit=True,
    )


def _check_template(tokenizer, rows):
    from trl.chat_template_utils import get_training_chat_template

    patched = get_training_chat_template(tokenizer)
    if patched:
        tokenizer.chat_template = patched
    for row in rows:
        tokens = tokenizer.apply_chat_template(
            row["messages"], tools=row["tools"], tokenize=True,
            return_dict=True, return_assistant_tokens_mask=True,
        )
        if len(tokens["input_ids"]) > MAX_LENGTH:
            raise SystemExit(f"{row['id']} exceeds {MAX_LENGTH} tokens")
        mask = tokens.get("assistant_masks")
        if not mask or not any(mask):
            raise SystemExit(f"{row['id']} has no assistant loss mask")


def _train(mode, root, digest, torch, gpu_name):
    from datasets import Dataset
    from trl import SFTConfig, SFTTrainer
    from unsloth import FastLanguageModel

    train_rows = load_jsonl(root / "data" / "processed" / "train.jsonl")
    val_rows = load_jsonl(root / "data" / "processed" / "val.jsonl")
    rows = train_rows[:1] if mode == "smoke" else train_rows
    model, tokenizer = _load_model()
    _check_template(tokenizer, train_rows + val_rows)
    model = FastLanguageModel.get_peft_model(
        model,
        r=8,
        lora_alpha=16,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=42,
    )
    output = root / "outputs" / ("smoke" if mode == "smoke"
                                  else "airport_mrt_adapter")
    config = SFTConfig(
        output_dir=str(output),
        max_length=MAX_LENGTH,
        per_device_train_batch_size=1,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=1 if mode == "smoke" else 4,
        learning_rate=1e-4,
        num_train_epochs=1,
        max_steps=1 if mode == "smoke" else -1,
        eval_strategy="no" if mode == "smoke" else "epoch",
        save_strategy="no" if mode == "smoke" else "epoch",
        assistant_only_loss=True,
        packing=False,
        seed=42,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        report_to="none",
    )
    trainer = SFTTrainer(
        model=model,
        args=config,
        train_dataset=Dataset.from_list(
            [{"messages": row["messages"], "tools": row["tools"]}
             for row in rows], on_mixed_types="use_json"),
        eval_dataset=None if mode == "smoke" else Dataset.from_list(
            [{"messages": row["messages"], "tools": row["tools"]}
             for row in val_rows], on_mixed_types="use_json"),
        processing_class=tokenizer,
    )
    trainer.train()
    trainer.save_model(str(output / "adapter"))
    tokenizer.save_pretrained(str(output / "adapter"))
    record = {
        "dataset_sha256": digest,
        "adapter_reloaded": False,
        "model_id": MODEL_ID,
        "gpu": gpu_name,
        "python": platform.python_version(),
        "torch": torch.__version__,
        "max_length": MAX_LENGTH,
        "mode": mode,
    }
    for package in ("unsloth", "trl", "transformers", "datasets", "peft"):
        module = __import__(package)
        record[package] = getattr(module, "__version__", "unknown")
    (output / "status.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{mode} adapter saved to {output / 'adapter'}")


def _verify_adapter(root, digest):
    from peft import PeftModel

    marker = root / "outputs" / "smoke" / "status.json"
    if not marker.exists():
        raise SystemExit("run --smoke first")
    status = json.loads(marker.read_text(encoding="utf-8"))
    if status.get("dataset_sha256") != digest:
        raise SystemExit("training data changed after smoke run")
    model, _ = _load_model()
    adapter = PeftModel.from_pretrained(
        model, str(root / "outputs" / "smoke" / "adapter"))
    if not adapter.peft_config:
        raise SystemExit("adapter reload failed")
    status["adapter_reloaded"] = True
    marker.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print("smoke adapter reloaded successfully")


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--smoke", action="store_true")
    mode.add_argument("--verify-adapter", action="store_true")
    mode.add_argument("--train", action="store_true")
    args = parser.parse_args()
    errors = validate_outputs(ROOT)
    if errors:
        raise SystemExit("data check failed:\n" + "\n".join(errors))
    digest = dataset_digest(ROOT)
    if args.check:
        print(f"data gate passed: {digest}")
        return
    if args.train:
        errors = check_training_gate(ROOT, digest)
        if errors:
            raise SystemExit("; ".join(errors))

    # The import happens only after all CPU-side gates pass.
    from unsloth import FastLanguageModel  # noqa: F401
    import torch

    gpu_name = _assert_gpu(torch)
    if args.verify_adapter:
        _verify_adapter(ROOT, digest)
    else:
        _train("smoke" if args.smoke else "train", ROOT, digest,
               torch, gpu_name)


if __name__ == "__main__":
    main()
