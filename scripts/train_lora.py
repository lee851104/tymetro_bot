"""QLoRA entry point for the RTX 4060 Windows or Linux machine.

No GPU libraries are imported by ``--check``. Always run smoke, reload,
then train; a data change invalidates the smoke marker.
"""

import argparse
import hashlib
import json
import math
import platform
import statistics
from pathlib import Path

from scripts.validate_data import load_jsonl
from scripts.validate_training import validate_bundle


ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "unsloth/Qwen3-4B-Instruct-2507-bnb-4bit"
MAX_LENGTH = 1024
CHAT_TEMPLATE = ROOT / "config/qwen3_instruct_chat_template.jinja"
TRAIN_CONFIG = {"model_id": MODEL_ID, "max_length": MAX_LENGTH,
                "lora_rank": 8, "lora_alpha": 16, "learning_rate": 1e-4,
                "warmup_steps": 2, "smoke_warmup_steps": 0,
                "assistant_only_loss": True, "seed": 42, "schema_version": 2}


def dataset_digest(root=ROOT, data_dir=None):
    digest = hashlib.sha256()
    for name in ("train.jsonl", "val.jsonl"):
        digest.update((Path(data_dir) if data_dir else Path(root) / "data/training").joinpath(name).read_bytes())
    return digest.hexdigest()


def config_digest():
    payload = {**TRAIN_CONFIG, "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "chat_template_sha256": hashlib.sha256(CHAT_TEMPLATE.read_bytes()).hexdigest()}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def check_training_gate(root, digest, configuration=None):
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
    if status.get("config_sha256") != (configuration or config_digest()):
        return ["training configuration changed after smoke run"]
    if not status.get("reload_forward_finite"):
        return ["adapter must pass a finite forward check after reload"]
    if not status.get("adapter_updated"):
        return ["smoke run must update adapter weights"]
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

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=MODEL_ID,
        max_seq_length=MAX_LENGTH,
        dtype=None,
        load_in_4bit=True,
    )
    tokenizer.chat_template = CHAT_TEMPLATE.read_text(encoding="utf-8")
    return model, tokenizer


def encode_conversation(tokenizer, row):
    """Mask each assistant span using the model's unmodified chat template.

    Pre-tokenizing keeps nested tool JSON out of Arrow schema inference and
    works with TRL 0.24 / datasets 4.3 as required by the installed Unsloth.
    Every prefix is compared with the complete conversation before masking.
    """
    ids = tokenizer.apply_chat_template(row["messages"], tools=row["tools"], tokenize=True, return_dict=False,
                                        add_generation_prompt=False)
    mask = [0] * len(ids)
    for index, message in enumerate(row["messages"]):
        if message["role"] != "assistant":
            continue
        prefix = tokenizer.apply_chat_template(row["messages"][:index],
                    tools=row["tools"], tokenize=True, return_dict=False, add_generation_prompt=True)
        through = tokenizer.apply_chat_template(row["messages"][:index + 1],
                    tools=row["tools"], tokenize=True, return_dict=False, add_generation_prompt=False)
        if ids[:len(prefix)] != prefix or ids[:len(through)] != through:
            raise SystemExit(f"{row['id']}: non-prefix-preserving template")
        if len(through) <= len(prefix):
            raise SystemExit(f"{row['id']}: empty assistant turn {index}")
        mask[len(prefix):len(through)] = [1] * (len(through) - len(prefix))
    return {"input_ids": ids, "assistant_masks": mask}


def _check_template(tokenizer, rows):
    lengths = {}
    assistant_turns = 0
    for row in rows:
        tokens = encode_conversation(tokenizer, row)
        if len(tokens["input_ids"]) > MAX_LENGTH:
            raise SystemExit(f"{row['id']} exceeds {MAX_LENGTH} tokens")
        mask = tokens.get("assistant_masks")
        if not mask or not any(mask):
            raise SystemExit(f"{row['id']} has no assistant loss mask")
        # A final answer having loss is insufficient: tool calls need loss too.
        covered = set()
        for index, message in enumerate(row["messages"]):
            if message["role"] != "assistant":
                continue
            prefix = tokenizer.apply_chat_template(row["messages"][:index],
                       tools=row["tools"], tokenize=True, return_dict=False, add_generation_prompt=True)
            through = tokenizer.apply_chat_template(row["messages"][:index + 1],
                        tools=row["tools"], tokenize=True, return_dict=False, add_generation_prompt=False)
            if tokens["input_ids"][:len(prefix)] != prefix or tokens["input_ids"][:len(through)] != through:
                raise SystemExit(f"{row['id']}: non-prefix-preserving template")
            if not any(mask[len(prefix):len(through)]):
                raise SystemExit(f"{row['id']}: assistant turn {index} has no loss (including tool calls)")
            covered.update(range(len(prefix), len(through)))
            assistant_turns += 1
        if any(value and index not in covered for index, value in enumerate(mask)):
            raise SystemExit(f"{row['id']}: loss mask includes non-assistant tokens")
        lengths[row["id"]] = len(tokens["input_ids"])
    report = {"records": len(rows), "assistant_turns": assistant_turns,
              "min_tokens": min(lengths.values()), "median_tokens": statistics.median(lengths.values()),
              "max_tokens": max(lengths.values()), "lengths": lengths,
              "config_sha256": config_digest()}
    print(f"Template checked: {len(rows)} records, {assistant_turns} assistant turns, max {report['max_tokens']} tokens")
    return report


def _audit_collator(trainer, tokenizer, train_rows, val_rows):
    """Inspect the labels actually emitted by TRL, not just our input masks."""
    checked = 0
    supervised = 0
    examples = []
    for partition, dataset, rows in (("train", trainer.train_dataset, train_rows),
                                     ("validation", trainer.eval_dataset, val_rows)):
        if dataset is None:
            continue
        if len(dataset) != len(rows):
            raise SystemExit("trainer dataset count changed before training")
        for index, row in enumerate(rows):
            encoded = encode_conversation(tokenizer, row)
            batch = trainer.data_collator([dataset[index]])
            ids = batch["input_ids"][0].tolist()
            labels = batch["labels"][0].tolist()
            length = len(encoded["input_ids"])
            expected = [token if mask else -100 for token, mask in
                        zip(encoded["input_ids"], encoded["assistant_masks"])]
            if ids[:length] != encoded["input_ids"] or labels[:length] != expected:
                raise SystemExit(f"{row['id']}: actual collator labels differ from assistant-only mask")
            if any(label != -100 for label in labels[length:]):
                raise SystemExit(f"{row['id']}: padding contributes to loss")
            kept = [token for token in labels if token != -100]
            supervised += len(kept)
            checked += 1
            if len(examples) < 3:
                examples.append({"id": row["id"], "partition": partition,
                                 "tokens": length, "supervised_tokens": len(kept),
                                 "decoded_supervised": tokenizer.decode(kept)})
    return {"passed": True, "records_checked": checked,
            "supervised_tokens": supervised, "examples": examples}


def _train(mode, root, data_dir, digest, torch, gpu_name):
    from datasets import Dataset
    from trl import SFTConfig, SFTTrainer
    from unsloth import FastLanguageModel

    train_rows = load_jsonl(data_dir / "train.jsonl")
    val_rows = load_jsonl(data_dir / "val.jsonl")
    rows = [r for r in train_rows if r["id"] in {"001", "005", "T012"}] if mode == "smoke" else train_rows
    model, tokenizer = _load_model()
    template_report = _check_template(tokenizer, train_rows + val_rows)
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
    trainable_parameters, total_parameters = model.get_nb_trainable_parameters()
    baseline_allocated = torch.cuda.memory_allocated() / 1024**3
    baseline_reserved = torch.cuda.memory_reserved() / 1024**3
    output = root / "outputs" / ("smoke" if mode == "smoke"
                                  else "airport_mrt_adapter")
    config = SFTConfig(
        output_dir=str(output),
        max_length=MAX_LENGTH,
        per_device_train_batch_size=1,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=len(rows) if mode == "smoke" else 4,
        learning_rate=1e-4,
        warmup_steps=0 if mode == "smoke" else 2,
        warmup_ratio=None,
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
        dataloader_num_workers=0,
        dataset_num_proc=1,
        logging_steps=1,
    )
    trainer = SFTTrainer(
        model=model,
        args=config,
        train_dataset=Dataset.from_list([
            {**encode_conversation(tokenizer, row), "messages": row["messages"]} for row in rows]),
        eval_dataset=None if mode == "smoke" else Dataset.from_list([
            {**encode_conversation(tokenizer, row), "messages": row["messages"]} for row in val_rows]),
        processing_class=tokenizer,
    )
    resolved_warmup_steps = trainer.args.get_warmup_steps(math.ceil(len(rows) / config.gradient_accumulation_steps))
    if resolved_warmup_steps != (0 if mode == "smoke" else 2):
        raise SystemExit("training library changed the requested warmup settings")
    mask_audit = _audit_collator(trainer, tokenizer, rows, [] if mode == "smoke" else val_rows)
    output.mkdir(parents=True, exist_ok=True)
    (output / "collator_audit.json").write_text(
        json.dumps(mask_audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Actual collator labels verified: {mask_audit['records_checked']} records", flush=True)
    initial_eval_metrics = trainer.evaluate() if mode == "train" else None
    initial_weights = {name: parameter.detach().cpu().clone()
                       for name, parameter in model.named_parameters() if "lora_B" in name}
    torch.cuda.reset_peak_memory_stats()
    training_result = trainer.train()
    adapter_updated = any(not torch.equal(initial_weights[name], parameter.detach().cpu())
                          for name, parameter in model.named_parameters() if name in initial_weights)
    if not adapter_updated or not math.isfinite(training_result.metrics["train_loss"]):
        raise SystemExit("training did not produce a finite loss and changed adapter weights")
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
        "adapter_updated": adapter_updated,
        "warmup_steps": resolved_warmup_steps,
        "config_sha256": config_digest(),
        "train_count": len(rows), "validation_count": 0 if mode == "smoke" else len(val_rows),
        "trainable_parameters": trainable_parameters, "total_parameters": total_parameters,
        "effective_batch_size": config.per_device_train_batch_size * config.gradient_accumulation_steps,
        "optimizer": str(trainer.args.optim), "lr_scheduler": str(trainer.args.lr_scheduler_type),
        "seed": trainer.args.seed, "global_steps": trainer.state.global_step,
        "baseline_gpu_allocated_gb": round(baseline_allocated, 3),
        "baseline_gpu_reserved_gb": round(baseline_reserved, 3),
        "peak_gpu_allocated_gb": round(torch.cuda.max_memory_allocated() / 1024**3, 3),
        "peak_gpu_reserved_gb": round(torch.cuda.max_memory_reserved() / 1024**3, 3),
        "collator_audit_passed": mask_audit["passed"],
        "initial_eval_metrics": initial_eval_metrics,
        "log_history": trainer.state.log_history,
        "metrics": training_result.metrics,
        "template_report": template_report,
    }
    for package in ("unsloth", "trl", "transformers", "datasets", "peft"):
        module = __import__(package)
        record[package] = getattr(module, "__version__", "unknown")
    (output / "status.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{mode} adapter saved to {output / 'adapter'}")


def _verify_adapter(root, digest):
    from peft import PeftModel
    from unsloth import FastLanguageModel
    import torch

    marker = root / "outputs" / "smoke" / "status.json"
    if not marker.exists():
        raise SystemExit("run --smoke first")
    status = json.loads(marker.read_text(encoding="utf-8"))
    if status.get("dataset_sha256") != digest:
        raise SystemExit("training data changed after smoke run")
    if status.get("config_sha256") != config_digest():
        raise SystemExit("training configuration changed after smoke run")
    model, tokenizer = _load_model()
    adapter = PeftModel.from_pretrained(
        model, str(root / "outputs" / "smoke" / "adapter"))
    if not adapter.peft_config:
        raise SystemExit("adapter reload failed")
    FastLanguageModel.for_inference(adapter)
    inputs = tokenizer("請用繁體中文回答：你好", return_tensors="pt").to("cuda")
    with torch.inference_mode():
        logits = adapter(**inputs).logits
    if not torch.isfinite(logits).all():
        raise SystemExit("reloaded adapter produced non-finite logits")
    status["reload_forward_finite"] = True
    status["adapter_reloaded"] = True
    marker.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print("smoke adapter reloaded successfully")


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--check-tokenizer", action="store_true")
    mode.add_argument("--smoke", action="store_true")
    mode.add_argument("--verify-adapter", action="store_true")
    mode.add_argument("--train", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/training")
    args = parser.parse_args()
    errors = validate_bundle(ROOT, args.data_dir)
    if errors:
        raise SystemExit("data check failed:\n" + "\n".join(errors))
    digest = dataset_digest(ROOT, args.data_dir)
    if args.check:
        print(f"data gate passed: {digest}")
        return
    if args.check_tokenizer:
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
        tokenizer.chat_template = CHAT_TEMPLATE.read_text(encoding="utf-8")
        rows = load_jsonl(args.data_dir / "train.jsonl") + load_jsonl(args.data_dir / "val.jsonl")
        report = _check_template(tokenizer, rows)
        report["dataset_sha256"] = digest
        (ROOT / "outputs").mkdir(exist_ok=True)
        (ROOT / "outputs/tokenizer_check.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
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
        _train("smoke" if args.smoke else "train", ROOT, args.data_dir, digest,
               torch, gpu_name)


if __name__ == "__main__":
    main()
