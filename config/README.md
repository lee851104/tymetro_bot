# 模型格式

`qwen3_instruct_chat_template.jinja` 取自 Qwen 原模型 `Qwen/Qwen3-4B-Instruct-2507` 的 `tokenizer_config.json`，修訂 `cdbee75f17c01a7cc42f958dc650907174af0554`，2026-09-21 擷取，Apache-2.0 授權。

來源：https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507/blob/cdbee75f17c01a7cc42f958dc650907174af0554/tokenizer_config.json

本次下載的 Unsloth 量化模型附帶另一份含 thinking 區塊的模板，會因 assistant 在對話中的位置改變輸出。訓練、基礎模型驗證、adapter 驗證都明確套用這份官方 Instruct 模板，並把雜湊納入試訓檢查。模板內容未改寫；loss 遮罩在 token 層依每段 assistant 的完整前綴產生。

## 重建本機環境

`requirements-windows.lock.txt` 記錄本次 Windows、Python 3.11、CUDA 13.0 環境的套件版本。已確認本機 NVIDIA 驅動可執行 CUDA；在其他電腦需先檢查驅動與 GPU。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r config/requirements-windows.lock.txt --extra-index-url https://download.pytorch.org/whl/cu130
.\.venv\Scripts\python.exe -m pip check
```

訓練入口與下載模型的命令見[開發與重現指南](../docs/development.md)。鎖定檔僅用於重現這次環境，不表示其他作業系統可直接使用。
