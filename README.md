# 機場捷運問答 LoRA 試訓專案

本專案以 50 題站務審稿資料準備 Qwen3 4B Instruct 的 QLoRA 試訓。目標是練習繁體中文站務回答、必要資訊追問及查班工具的使用流程。它還不是可供旅客使用的服務：真實班次、票價與營運異動必須由正式資料來源查詢。

## 目前狀態

- 五份 `airport_mrt_qa_*.md` 是審稿原件；013、017、047、050 已排除。
- `data/processed/all.jsonl` 有 50 筆對話；`train.jsonl` 40 筆、`val.jsonl` 10 筆，依情境群組切分。`data/split_manifest.json` 固定題號與種子 42。
- `data/eval/unseen_cases.jsonl` 有 20 題獨立測試題，不用於訓練或調參。
- `src/schedule.py` 是**固定模擬資料**的查班邏輯，沒有接上桃捷即時資料。模擬班次的日期故意設為 2099 年，不能提供旅客使用。
- 本機僅有 940MX 2 GB；GPU 試訓應在新電腦 RTX 4060 8 GB 執行。尚未產生 adapter。

## 資料流程（任何電腦均可跑）

需要 Python 3.11 以上，資料準備與測試只用標準函式庫。在專案根目錄執行：

```bash
python -m scripts.prepare_data
python -m scripts.validate_data
python -m unittest discover -s tests -v
python -m scripts.train_lora --check
```

轉換程式只抓每題 `**對話**` 的旅客與機器人語句。審稿欄、來源連結、題號標題不進訓練資料。001、002、003、004、042 的班次時間只出現在**工具回傳後的模擬對話**；005 的票價與 011 的航廈未確定時不猜答案。不得把原稿的 `{{...}}` 複製進資料集。

## 新電腦上的試訓順序

建議在 WSL2 Ubuntu 的 Linux 檔案系統 clone 專案，使用 Python 3.11 `venv`，依 [Unsloth 官方安裝說明](https://unsloth.ai/docs/get-started/fine-tuning-for-beginners/unsloth-requirements) 安裝 GPU 依賴。先確認 `nvidia-smi` 顯示 RTX 4060 8 GB，再依序執行：

```bash
python -m scripts.prepare_data
python -m unittest discover -s tests -v
python -m scripts.train_lora --check
python -m scripts.train_lora --smoke
python -m scripts.train_lora --verify-adapter
python -m scripts.train_lora --train
```

`--smoke` 載入 4-bit 模型，使用一筆資料跑一個訓練步並儲存 adapter。`--verify-adapter` 以新程序重新載入；只有兩步成功且資料未改動，`--train` 才會執行一個 epoch。程式會檢查 chat template 是否產生 assistant loss mask，並阻止樣本被 1024 tokens 截斷。設定依 `airport_mrt_lora_training_plan.md`：batch 1、累積 4、rank 8、alpha 16、學習率 `1e-4`、種子 42。顯存不足時先降低序列長度或 LoRA rank，記錄實際版本與設定。

模型權重、快取、adapter 和訓練輸出不進 Git。`data/` 則刻意納入 Git，讓新電腦 clone 後有相同的資料與切分。正式資料來源接入、原模型與 LoRA 的對照測試及上線前事實複核，仍需另行完成。詳見 [資料檢查報告](reports/data_check.md)。

## 主要檔案

| 路徑 | 用途 |
| --- | --- |
| `scripts/prepare_data.py` | 轉換審稿原件、處理佔位符、固定切分 |
| `scripts/validate_data.py` | 檢查 JSONL、欄位、角色、工具回傳與切分 |
| `src/schedule.py` | 以模擬資料挑選可停靠班次與轉乘方案 |
| `scripts/train_lora.py` | 新電腦上的 GPU 冒煙測試與一輪試訓 |
| `tests/` | 不需 GPU 的資料及查班測試 |
| `data/eval/unseen_cases.jsonl` | 不參與訓練的 20 題最終測試 |
