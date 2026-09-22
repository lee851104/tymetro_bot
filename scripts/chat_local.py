"""Ask the local model through exactly the same path used in evaluation."""

import argparse
import json
from datetime import datetime
from pathlib import Path

from src.bot_tools import SYSTEM_PROMPT, TOOL_SCHEMA
from src.model_inference import load_generator, run_turn
from src.timetable import TAIPEI


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--adapter", type=Path, default=Path("outputs/airport_mrt_adapter/adapter"))
    parser.add_argument("--base", action="store_true")
    parser.add_argument("--at", default=None, help="ISO 8601 with timezone; default is Taiwan now")
    parser.add_argument("--trace", action="store_true")
    args = parser.parse_args()
    at = datetime.fromisoformat(args.at) if args.at else datetime.now(TAIPEI)
    if at.tzinfo is None:
        parser.error("--at requires a timezone")
    messages = [{"role": "system", "content": SYSTEM_PROMPT +
                 "\n目前臺灣時間：" + at.astimezone(TAIPEI).isoformat(timespec="seconds")},
                {"role": "user", "content": args.question}]
    generate, evidence = load_generator(None if args.base else args.adapter)
    result = run_turn(generate, messages, [TOOL_SCHEMA])
    if args.trace:
        print(json.dumps({"model_evidence": evidence, **result}, ensure_ascii=False, indent=2))
    elif result.get("tool_error"):
        print("模型未完成查詢，請改用離線查班工具或洽站務人員。")
    else:
        print(result.get("final_output", result["first_output"]).removesuffix("<|im_end|>").strip())


if __name__ == "__main__":
    main()
