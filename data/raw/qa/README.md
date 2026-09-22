# QA 原稿

本目錄保存五份站務問答 Markdown，保留原始題號、修訂與來源紀錄。依既有排除規則，資料準備程式匯入 50 題；檔名表示原始批次，實際題號包含補充與替換題。

| 原稿 | 原始批次 |
| --- | --- |
| [airport_mrt_qa_001-010.md](airport_mrt_qa_001-010.md) | 第一批 |
| [airport_mrt_qa_011-020.md](airport_mrt_qa_011-020.md) | 第二批 |
| [airport_mrt_qa_021-030.md](airport_mrt_qa_021-030.md) | 第三批 |
| [airport_mrt_qa_031-040.md](airport_mrt_qa_031-040.md) | 第四批 |
| [airport_mrt_qa_041-050.md](airport_mrt_qa_041-050.md) | 第五批 |

## 資料流向

- `scripts/prepare_data.py`：讀取本目錄，產生 `data/processed/` 的歷史模擬資料（40 筆訓練、10 筆驗證）。
- `scripts/prepare_training.py`：讀取同一份原稿，搭配 `data/training_cases.json` 與本機班表，產生 `data/training/` 的 87 筆現行資料（70 筆訓練、17 筆驗證）。
- 原稿保留原文；能力範圍調整與動態班次替換由轉換程式處理。票務及營運規則的原稿敘述不視為即時官方資訊。

執行指令見[開發與重現指南](../../../docs/development.md)，現行資料說明見[訓練資料](../../training/README.md)。
