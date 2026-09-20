# 機場捷運問答機器人：第一輪 LoRA 訓練計畫

更新日期：2026-09-20

## 目標與範圍

用目前 50 題站務問答，先驗證模型能否用繁體中文回答全線常見問題，並在班次問題中正確要求查詢、解讀查詢結果。這是**試訓**，不是可直接上線的完整知識庫。最近一班車、票價、營運異動等會變動的資訊，正式使用時必須由外部資料源提供，不能讓 LoRA 背時刻表。

目前原稿是同目錄的五份 `airport_mrt_qa_*.md`。保留 50 題；047、050 等被刪除的題號不再匯入。

## 1. 工具與模型決定

**採用 Hugging Face 上的模型，由 Unsloth 執行 QLoRA。** Hugging Face 是模型託管與下載來源；Unsloth 是載入、4-bit 量化與微調工具。訓練程式指定模型 ID 時，會自動下載到 Hugging Face 快取，通常不用先手動下載模型。若要離線訓練，再另外用 `hf download` 取得固定版本。

第一輪模型：[`unsloth/Qwen3-4B-Instruct-2507-bnb-4bit`](https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-bnb-4bit)。它是 Qwen3 4B Instruct 的 4-bit 版本；[原模型卡](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)標示 4B、支援工具使用，授權為 Apache 2.0。以 RTX 4060 8 GB、主記憶體 32 GB 做短對話 QLoRA 試訓。Unsloth 的[顯存表](https://unsloth.ai/docs/get-started/fine-tuning-for-beginners/unsloth-requirements)是最低值，不保證任何參數設定都能在 8 GB 執行；因此先做一筆資料的載入與單步訓練測試。

環境建議：Windows 11 + WSL2 Ubuntu、NVIDIA 驅動、Python 3.11 `venv`。先依[Unsloth 官方安裝與需求文件](https://unsloth.ai/docs/get-started/fine-tuning-for-beginners/unsloth-requirements)安裝；在新機記錄 `nvidia-smi`、Python、PyTorch、CUDA、Unsloth 和 TRL 版本。等單步訓練通過後，將版本寫入鎖定檔。訓練資料、模型快取與輸出放在 WSL 的 Linux 檔案系統，並預留足夠磁碟空間。

## 2. 資料準備：先完成，再切分

1. 五份 Markdown 保留作人工審稿原件。另做轉換程式，將每個題號轉為一筆對話資料；同一題內的追問仍放在同一筆，不拆到不同集合。移除來源網址、審核文字、題號標題等非對話內容。
2. 逐題確認最終回答。現有 `{{發車時間}}` 等佔位符不能直接進訓練集；它們必須改成具體的工具呼叫與模擬回傳，或改為「先詢問起站／說明需查詢」的回答。檢查沒有過期時刻、未開通車站被寫成已營運，以及仍待確認的審稿註記。
3. 靜態題目使用 `messages` 對話格式。例如：

   ```json
   {"messages":[{"role":"user","content":"泰山貴和站去台北車站，可以等直達車嗎？"},{"role":"assistant","content":"A6 泰山貴和站沒有直達車停靠。請搭往台北方向的普通車。"}]}
   ```

4. 動態班次題目另外定義 `get_next_trains(起站, 目的站, 查詢時間)` 的資料契約，提供**固定的模擬回傳**：能到目的站的最近班次、下一班、車種、方向、預定或即時時間、轉乘、資料查詢時間與異動狀態。訓練樣本需包含「提出查詢 → 工具回傳 → 根據結果回答」完整對話；格式依 [TRL 工具呼叫資料規格](https://huggingface.co/docs/trl/dataset_formats)製作，並使用模型原本的 chat template。正式服務仍需實作此工具及資料來源。桃捷官網有[時刻表查詢](https://www.tymetro.com.tw/tymetro-new/tw/_pages/travel-guide/timetable-search.html)及[列車動態資訊](https://www.tymetro.com.tw/tymetro-new/tw/_pages/travel-guide/dynamictraininfo.php)，但要先確認實際可取得的欄位、更新頻率及使用方式；不能把預定班表稱作即時到站。
5. 轉換結果先做資料檢查：50 個不重複 ID、角色順序正確、每題有旅客問題和機器人回答、JSONL 可逐行解析、無 `{{...}}`、無審稿欄與來源欄、班次工具輸出包含資料時間及來源類型。

預計產物：`scripts/prepare_data.py`、`scripts/validate_data.py`、`data/processed/all.jsonl`、資料檢查報告。先用手工檢查至少 10 筆轉換結果，其中包含多輪題與班次題。

## 3. 切分與試題

- 將 50 題依**情境群組**切成 40 題訓練、10 題驗證，固定題號清單與亂數種子。相同目的或同一路線的改寫題不要分到兩邊。驗證題不用於梯度更新或人工改寫成訓練題。
- 另寫至少 20 題**全新**的最終測試，含旅客口語、省略起站、直達車不停靠、末班已過、轉乘、停駛、資料查不到、預定與即時資訊不一致。最終測試不能拿來調參。
- 比較未微調原模型與 LoRA 模型時，使用同一套 system prompt、工具回傳、chat template 與生成設定；只換 adapter。這樣才能知道改善是否來自微調。

預計產物：`data/processed/train.jsonl`、`data/processed/val.jsonl`、`data/eval/unseen_cases.jsonl`、`data/split_manifest.json`。

## 4. 先測程式，再訓練

先寫兩種測試，兩種都不需要 GPU：

1. **資料測試：** 轉換與切分後沒有重複、漏題、佔位符或訓練／驗證交叉；多輪對話仍完整。
2. **查班工具測試：** 使用固定班次資料，確認只回傳會停靠目的站的車，正確挑最近一班與下一班；跨日、末班已過、延誤、轉乘等待、資料過期及無資料時不捏造時間。

完成後先在新機做 GPU 冒煙測試：載入 4-bit 模型、套 LoRA、跑一筆前向計算與一個訓練步、存出並重新載入 adapter。遇到顯存不足，先把序列長度降到 1024、batch 設 1，再調整 LoRA rank；不要先改用更大模型。

## 5. 第一輪訓練設定

使用 Unsloth 載入 4-bit 模型，TRL `SFTTrainer` 接訓練與驗證資料。起始設定如下；以冒煙測試的顯存結果調整：

| 項目 | 起始值 |
| --- | --- |
| 方法 | QLoRA，僅訓練 adapter |
| 最長序列 | 1024 tokens；多輪題若被截斷，再測 1536 |
| 每裝置 batch | 1 |
| 梯度累積 | 4 |
| LoRA rank / alpha | 8 / 16 |
| 學習率 | `1e-4` |
| epoch | 先跑 1，最多比較到 2 |
| 隨機種子 | 42 |
| 檢查點 | 每個 epoch 記錄訓練與驗證 loss，保存 adapter |

訓練時只讓機器人回答部分計算 loss；若使用 TRL 的 `assistant_only_loss=True`，須先驗證該模型 chat template 能正確產生 assistant mask，不可直接假設設定生效。[TRL SFT 文件](https://huggingface.co/docs/trl/sft_trainer)說明此限制。50 題很少，loss 下降不代表會處理沒見過的站務問題；若驗證表現下降，就停在較早的檢查點。[Unsloth LoRA 參數說明](https://docs.unsloth.ai/basics/lora-parameters-encyclopedia)建議留意小資料過度擬合。

預計產物：`scripts/train_lora.py`、`outputs/airport_mrt_adapter/`、版本與參數紀錄。先保存 adapter，暫不合併成完整模型。

## 6. 驗收與下一輪

用未見過的測試題逐題記錄：起訖站與方向是否正確、直達／普通車停靠判斷、是否要求必要資訊、是否呼叫查班工具、是否忠實引用工具時間與資料類型、無資料時是否拒絕猜測、語氣是否符合站務回答。對照未微調模型；若只是背出訓練題句子，不能算成功。

第一輪的通過條件：資料檢查與查班工具測試全部通過；模型能成功載入、訓練及重新載入 adapter；新測試題中**不得捏造班次或把未開通站當已營運站**，其餘錯題有清楚分類。若這些條件未達成，先修資料或工具，再決定是否增加問答題；不要單靠增加 epoch 補救。

## 實作順序清單

- [ ] 在 4060 新機確認 CUDA 與 Unsloth 可用，記錄版本與顯存。
- [ ] 決定查班工具資料來源與回傳格式，做固定回傳的測試資料。
- [ ] 把 50 題轉為對話 JSONL，處理佔位符與審稿文字。
- [ ] 寫資料驗證與查班工具測試，全部通過。
- [ ] 固定 40／10 切分，另建立至少 20 題全新測試。
- [ ] 跑原模型基準測試。
- [ ] 跑單步 GPU 冒煙測試，再做 1～2 epoch QLoRA。
- [ ] 重新載入 adapter，與原模型用相同測試比較，保存錯題與結論。
