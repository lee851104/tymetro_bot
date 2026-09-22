# 依《學生實作本_T4.ipynb》調整第二輪流程

參考檔：專案根目錄 `學生實作本_T4.ipynb`，68 個儲存格；SHA-256：`921904e487ffa32d664886dd6365b94081e4fad924c6457d35af77d145b88b20`。檔案沒有保存執行輸出，因此教材內的耗時、顯存與成績不能當成本機實測。

教材中的 Colab 安裝指令、天文資料下載及刻意保留的 bug 未執行。採用的是資料檢查、隔離、對照與可追查的工作方式。

## 模組對照

| 教材 | 本專案採用方式與證據 |
| --- | --- |
| M1：GPU、4-bit 與 LoRA | 維持 Qwen3 4B、RTX 4060 8 GB、rank 8／alpha 16、batch 1／累積 4。記錄實際可訓練參數、優化器、起始與尖峰 allocated／reserved 顯存；不套用 T4 的精度、11B 視覺模型或 Colab 套件版本。 |
| M2：對話格式與 chat template | 使用 Qwen 原始模板；訓練完整對話不加 generation prompt，推論才加入。逐段驗證 assistant 回答及工具呼叫的 loss mask。 |
| M2-4：實際 collator 標籤 | 新增 `collator_audit.json`；比對 trainer 真正輸出的 input IDs 與 labels，逐筆確認 user／system／tool／padding 不計 loss，assistant 文字與工具呼叫有計 loss，保存解碼範例。 |
| M3：資料體檢 | 70 筆訓練／17 筆驗證；分別 44／11 個情境群組，含工具呼叫的對話 22／9 筆。各集合沒有完全重複對話或空文字訊息；檢查 ID、情境群組與完整對話內容沒有跨集合重疊。保留繁體中文、站碼、數字、時間與標點。 |
| M4：訓練與 validation loss | 先單步試訓、另開程序重載，再正式訓練 1 epoch。記錄訓練前的 validation loss、每步訓練 loss、epoch 結束的 validation loss，以及實際更新步數。單輪結果只能觀察變化，不能單憑 loss 證明沒有過擬合。 |
| M5：修正評估與對照 | 固定 8 題驗證案例與 greedy 解碼，包含原有 5 題及新增 3 題；重新取得原模型、舊 adapter、新 adapter 的結果。保留原始輸出與完整工具結果，人工看答案是否符合資料。 |
| M5-2：prompt 回音 | 依輸入 token 數切掉 prompt，再 decode 新 token；測試保證不靠字串 `assistant` 切分。 |
| M5-3：資料洩漏 | 使用訓練前就固定的群組切分，驗證題不回流訓練；獨立 20 題最終測試保持未使用。沒有把驗證成績包裝成最終泛化正確率。 |
| M5-4：明確解碼設定 | 共用 `do_sample=False`、256 新 token、2,048 推論 context；訓練 context 仍為 1,024。新版工具回傳較長，需要另外保留回答空間。 |
| M6：保存與實際使用 | 保留上一輪 adapter；只保存 adapter，不合併或上傳模型。載入時核對 PEFT、LoRA B 張量非零且有限，以及權重檔 SHA-256。 |
| A3：評估與使用共用程式 | `src/model_inference.py` 統一模型載入、生成、工具解析與呼叫；`scripts/evaluate_adapter.py` 和 `scripts/chat_local.py` 都呼叫同一份程式。 |

## 本專案評估什麼

1. **嚴格工具匹配**：名稱、起訖站、日期時間是否完全符合預期。
2. **工具結果等價**：另外接受「北車」和 A1 這類會產生相同工具結果的已核定暱稱；保留嚴格成績，不用新指標掩蓋差異。
3. **答案人工檢查**：有沒有捏造班次、忽略 3 分鐘提醒、推薦不停目的站的車、漏問不明航廈，或保證未取得的抵達／即時資訊。工具匹配不代表答案正確。
4. **訓練證據**：權重確實改變、儲存與重載成功、實際 labels 正確、有限 loss、資料與程式版本可追查。

此任務不用 BLEU／ROUGE 作主要成績。微調目標是站名辨識、追問、工具使用與依資料回答；班表和會變動的規則保存在可更新的外部資料。

## 保存位置

- 本輪輸入與對照：`outputs/round2_2026-09-22/`。
- 上輪模型：`outputs/airport_mrt_adapter_round1_2026-09-21/adapter/`。
- 本輪模型：完成後寫入 `outputs/airport_mrt_adapter/adapter/`。
- 每步 loss 與資源紀錄：完成後寫入 `outputs/airport_mrt_adapter/status.json`。

實驗結果另寫入 `reports/training_round2.md`；本文件描述流程，不提前宣稱訓練成功或品質改善。
