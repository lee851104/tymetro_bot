# 開發與重現指南

[返回專案介紹](../README.md)。本頁保留環境、資料重建、訓練與驗證細節；以下指令均在專案根目錄執行。GPU 套件安裝方式見 [Windows 環境說明](../config/README.md)。

## Qwen 模型測試介面（目前中文）

```powershell
.\.venv\Scripts\python.exe -m scripts.serve_demo --port 8765 --engine qwen
```

開啟 http://127.0.0.1:8765 。HTTP 介面使用 Python 標準函式庫；Qwen 使用專案 `.venv` 的 Unsloth／CUDA 與本機 RTX 4060，載入 `outputs/airport_mrt_adapter/adapter` 第二輪權重。模型與 tokenizer 從專案快取離線載入，不呼叫外部模型 API。

2026-09-22 介面已改為藍紫色的**路線選站＋班次卡片**：點起站／目的站後，可直接在 22 站路線圖選站，支援交換起訖、全部／普通／直達車及出發日期時間。手機自動改為四站一列。表單直接傳送 `{route: {origin, destination, train_type}, at}`，模型收到含日期與車種的明確問句；前端另核對 `confirmed_query`，條件不符時不顯示班次。詳見[視覺選站實測](../reports/visual_station_picker.md)。

- 聊天原文直接交給已訓練 Qwen；表單先轉成起訖查詢句，再交給同一模型。頁面會顯示模型載入狀態，目前依使用者要求先固定中文。
- 聊天與表單仍會經過 Qwen。班次回答改由應用程式核對完整起訖、日期、時間與車種後查班表產生；不把模型自行判定的「沒有車」或轉乘建議直接顯示給旅客。指定普通車／直達車會先篩選整天符合停靠規則的班次，再套用三分鐘緩衝與最近兩班限制。
- 原始模型輸出與模型工具呼叫留在可展開的除錯紀錄，另記錄 `grounding` 與 `answer_source`。此流程是程式核對，不代表模型權重已改善；詳細修正及實測見 [普通車查詢修正](../reports/commuter_query_fix.md)。
- 同一對話保留最近 3 輪；2048-token 設定超長時提示開新對話。GPU 請求一次處理一筆；新對話會清除網頁的對話識別，但已開始的生成可能仍需完成。
- `outputs/demo/qwen/model_status.json` 記錄實際權重雜湊與載入證據；`requests.jsonl` 保存本機問題與原始回覆供檢查，不自動加入訓練資料。
- 只監聽本機 `127.0.0.1`；`Ctrl+C` 停止。詳細驗證見 [Qwen 接線紀錄](../reports/qwen_demo_connection.md)。

不使用 GPU 的班表展示可明確選用 `--engine timetable`；目前介面固定中文，此模式不載入 Qwen／LoRA，車種篩選功能僅在 Qwen 模式開放。一次只啟動其中一種模式；介面的歷史紀錄見[展示介面紀錄](../reports/demo_interface.md)。

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_qwen_chat tests.test_model_inference tests.test_demo -v
```

## 資料與能力

- `data/raw/qa/`：五份 QA Markdown 原稿，保留原始題號與修訂來源；[原稿索引](../data/raw/qa/README.md)說明轉換流向。初版訓練設計另存於 [training-plan.md](training-plan.md)。
- `data/training/`：目前使用的 **87 筆 SFT 對話，70 筆訓練、17 筆驗證**，情境群組不跨集合。包含 50 題原稿改編與 37 題補充案例。
- `data/processed/`：保留原始 50 題轉換結果，含 2099 年模擬班次，供歷史稽核；目前訓練入口改用 `data/training/`。
- `data/eval/unseen_cases.jsonl`：20 題獨立最終測試，不用於準備資料、訓練或調參。
- `data/timetable/cache.json`：依使用者確認的 **一般平假日班表**，不納入特殊活動。涵蓋 2026-09-21～2026-10-04、22 站、51,916 筆站別發車紀錄，共 37 種站別模式；不是 51,916 班不同列車。原始官網資料另存 `official_cache.json`。詳見[離線班表說明](../data/timetable/README.md)。
- `data/timetable/calendar_2026.json`：依行政院 115 年辦公日曆整理全年 365 日，含 120 個放假日；不以星期一到五直接視為平日。日曆涵蓋全年不代表班表涵蓋全年。
- 工具支援指定起訖站與時間，篩選最近兩班**不需換車**的預定班次。Qwen 展示頁另支援普通車／直達車篩選；不需換車不等於直達車。沒有抵達時間、轉乘銜接或即時運行狀態；未建置的班表日期不自行補值。
- `data/station_aliases.json`：已接入使用者確認的暱稱與追問規則；模糊地區、航廈不明或站碼與站名衝突時先追問。
- 起訖查詢排除距查詢時間 **3 分鐘內（含剛好 3 分鐘）**發車的班次，提醒考慮較晚班次、避免趕車。若只剩即將發車的末班，明確告知沒有後續班次，不編造下一班。這是使用者指定的回覆政策，並非官方關門或步行時間。
- `data/knowledge/official_sources.json`：保存 10 個官方主題頁及 22 站頁面的正文、連結與來源雜湊；仍需整理適用條件，尚未整批用作回答或訓練。[來源與缺口清單](../reports/official_knowledge_coverage.md)。

目前是小規模試訓資料，尚不能宣稱上線品質。原稿中的票務、預辦登機、乘車規則及設施資訊仍須按最新官方公告複核。

2026-09-22 已參考使用者的《學生實作本_T4.ipynb》完成第二輪 QLoRA、實際 collator labels 核對與 adapter 重載。該輪訓練當時 61 項程式測試通過，訓練 18 步約 62 秒，驗證 loss 2.788 → 1.686。同一組驗證情境中，正確查工具由上一輪 2／7 增至 4／7，但完整回答人工檢查僅 2／8 通過，仍有錯誤轉乘與多餘追問。詳見[第二輪報告](../reports/training_round2.md)與[教材對照](../reports/notebook_training_review.md)；[第一輪紀錄](../reports/training_readiness.md)保留供追查。

第二輪[人工審查包](../data/review/README.md)的暱稱與混淆用語已依使用者修改接入，C15 不採用；補入 12 題暱稱、追問與上車緩衝案例。32 題回答範例未視為全部通過；官方規則由程式取得來源，使用者主要協助審查現場用語。

## 重建與檢查資料

Python 3.11 以上；以下資料流程只需標準函式庫：

```powershell
.\.venv\Scripts\python.exe -m scripts.prepare_data
.\.venv\Scripts\python.exe -m scripts.prepare_training
.\.venv\Scripts\python.exe -m scripts.validate_training
.\.venv\Scripts\python.exe -m scripts.profile_training
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m scripts.train_lora --check
```

每筆 JSONL 有 `messages`、`tools`、`id`、`scenario_group` 與 `provenance`。工具對話包含 system 時間、使用者提問、assistant 的 `tool_calls`、tool 的 JSON 回傳及 assistant 回答。程式從已確認的一般班表快取產生班次答案；兩筆故障案例透過缺少檔案重現失敗，不捏造列車時間。2026-09-22 的 87 筆資料已用於第二輪；tokenizer 檢查 120 段 assistant、最長 960 tokens，低於 1,024 上限，並逐筆核對 trainer 實際 labels。

`manifest.json` 記錄來源與輸出 SHA-256。更動來源、停靠規則或快取後須重建。檢查會比對訓練／驗證檔的完整內容，並拒絕群組重疊、角色錯序、未回應工具與缺少時間依據等情況。

## 本機 GPU

目前電腦已確認為 **RTX 4060 8 GB**，已通過 CUDA 矩陣運算。環境放在專案 `.venv`，不使用其他應用程式的 Python。

第一次重現請先依 [Windows 環境說明](../config/README.md)安裝依賴，再完成上方的資料檢查。下方 `--check-tokenizer` 取得 tokenizer，`--smoke` 在首次載入時下載基礎模型至 `HF_HOME`；因此第一次準備需要網路與模型儲存空間。若曾設定 `HF_HUB_OFFLINE` 或 `TRANSFORMERS_OFFLINE`，首次下載前需解除離線設定。

重新訓練前請先停止佔用同一張 GPU 的展示服務，並另存想保留的舊訓練成果；完整訓練會寫入 `outputs/airport_mrt_adapter/`。以下 `--verify-adapter` 驗證的是 smoke 試訓權重，完整訓練完成後再用後面的 adapter 評估指令確認新成果可載入。

本專案依照 [Unsloth Windows 原生安裝說明](https://unsloth.ai/docs/get-started/install/windows-installation)建立環境。完整測試結果、版本及剩餘工作見 [本機試訓報告](../reports/training_readiness.md)。

```powershell
$env:HF_HOME = "$PWD\models\huggingface"
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe -m scripts.train_lora --check-tokenizer
.\.venv\Scripts\python.exe -m scripts.train_lora --smoke
.\.venv\Scripts\python.exe -m scripts.train_lora --verify-adapter
.\.venv\Scripts\python.exe -m scripts.train_lora --train
```

`--smoke` 用一般問答、查班成功與故障三筆資料累積一個訓練步，停用暖身並確認 adapter 權重確實改變。`--verify-adapter` 在新程序載入 adapter 並檢查前向結果是否有限值。資料或程式設定改動後須重新試訓；完整一輪使用 batch 1、累積 4、rank 8、alpha 16、學習率 `1e-4`、暖身 2 步、種子 42。

訓練前逐筆檢查實際 token 長度，每一段 assistant 回答和工具呼叫均參與 loss，使用者、系統和工具回傳均遮罩。使用模型原始 chat template，比對每段前綴後預先產生 token 與遮罩，避免不同版本的套件改寫工具 JSON。超出最大長度時直接停止，不截斷資料。

## 驗證原模型與 adapter

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_adapter --base --output outputs/eval/base.json
.\.venv\Scripts\python.exe -m scripts.evaluate_adapter --adapter outputs/airport_mrt_adapter/adapter --output outputs/eval/adapter.json
```

預設只測 5 題固定驗證題，使用相同提示詞、工具及生成設定，記錄工具參數匹配與完整回答。第二輪以 `--ids 002 003 004 V001 V004 A004 A008 B002` 比較 8 題，另保留接受暱稱的等價工具分數及人工檢查。這不是正式正確率；最終 20 題保留到模型與設定決定後再評估。

`src/model_inference.py` 統一模型載入、生成與工具呼叫；評估與實驗用 `scripts.chat_local` 共用此入口。目前模型仍會曲解工具結果，請勿直接作為旅客服務使用。

## 離線查班

```powershell
.\.venv\Scripts\python.exe -m scripts.query_timetable --origin A8 --destination A10 --at 2026-09-21T10:00:00+08:00 --format text
```

應用程式使用 `src.bot_tools.dispatch_tool` 呼叫同一份工具契約。完整來源圖例、日期範圍、擷取時間與原始 HTML 雜湊保存在快取；提供模型的回傳只保留必要欄位。

平假日依行政院日曆，平日基準為 9/21、假日基準為無活動調整的 10/17，並與使用者圖片核對。以 `.venv\Scripts\python.exe -m scripts.build_normal_timetable` 重建一般班表，再執行 `scripts.prepare_training` 同步訓練案例。下載官網只更新 `official_cache.json`，不會直接覆蓋一般班表設定。

| 檔案 | 用途 |
| --- | --- |
| `scripts/prepare_training.py` | 轉換原稿、接上真實工具回傳、加入補充案例 |
| `data/training_cases.json` | 可人工修改的補充案例與固定切分 |
| `scripts/validate_training.py` | 檢查來源、切分、角色及工具資料 |
| `src/bot_tools.py` | 訓練和應用程式共用的離線查班 API |
| `scripts/train_lora.py` | tokenizer 檢查、QLoRA 試訓、重載與完整一輪 |
| `scripts/evaluate_adapter.py` | 原模型與 adapter 的固定驗證題比較 |
| `scripts/fetch_timetable.py` | 下載指定日期的官方班表 |
| `scripts/build_normal_timetable.py` | 依行政院日曆建立不含特殊活動的一般班表 |
| `src/service_calendar.py` | 平日、假日與補班覆寫判定；未提供年份不猜測 |
| `src/station_routes.py` | 停靠站及官方圖例核對 |

模型、下載快取與 adapter 在 `models/`、`outputs/`，不進 Git。資料和切分保留在專案中，供版本追蹤。

## 參考流程

已對照使用者提供的 [T4 實作教材](../reports/notebook_training_review.md)及 [Astronomy LoRA 原始專案](../reports/astronomy_lora_review.md)。後者固定修訂保存於 `outputs/references/astronomy/`。新增資料體檢會產生 `reports/training_data_profile.json`，用於確認實際資料分布；不會修改資料或啟動 GPU 訓練。

## README 示意動畫

`docs/assets/query-flow.gif` 是四步驟示意動畫，非介面錄影。產生時以固定日期查詢本機班表，將實際回傳的兩個時間填入最後一格；`query-flow-poster.png` 提供靜態版本。若班表移除該日期，需一併修改腳本範例及 README 文字。

Pillow 僅為產生文件圖片所需，無 GPU 展示服務不需要安裝它：

```powershell
.\.venv\Scripts\python.exe -m pip install Pillow
.\.venv\Scripts\python.exe -m scripts.render_readme_animation
```

預設使用 Windows 微軟正黑體；其他系統可用 `--font` 與 `--bold-font` 指定支援繁體中文的字型檔案。
