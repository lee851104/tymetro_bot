# Astronomy LoRA 原始專案對照

核對日期：2026-09-22。參考 [AIOmarRehan 原始專案](https://github.com/AIOmarRehan/Unsloth_Llama_3.2_11B_Vision_Instruct_Astronomy/tree/6b8d73fbb51c3776b3a2d34064f68481dbf37f0d)，固定修訂 `6b8d73fbb51c3776b3a2d34064f68481dbf37f0d`。

已下載至 `outputs/references/astronomy/`，閱讀 README、訓練／部署 notebook、app.py、依賴清單與上游範例。來源檔案雜湊及證據位置保存於 [來源紀錄](references/astronomy_source.json)。沒有執行其安裝、下載模型、訓練、公開介面或上傳指令。

## 適合採用的部分

這是 Llama 3.2 11B 視覺模型的天文影像描述範例，與《學生實作本_T4.ipynb》的訓練程式與問題能相互對照。我們採用資料體檢、4-bit LoRA、梯度累積、gradient checkpointing、資源量測與保存／重載模型的方法；保留機捷專案的 Qwen3 4B、繁體中文和工具對話格式。

| 項目 | 天文原始設定／紀錄 | 機捷目前做法 |
| --- | --- | --- |
| 模型與任務 | 11B 視覺模型、圖片配一句描述 | 4B 文字模型、多輪追問與工具使用 |
| LoRA | rank 16、alpha 16，視覺與語言層皆訓練 | rank 8、alpha 16，attention 與 MLP 投影層 |
| 訓練量 | batch 2 × 累積 4，30 updates；紀錄顯示訓練 250 筆 | batch 1 × 累積 4，70 筆、1 epoch、18 updates |
| 優化 | 學習率 `2e-4`、AdamW 8-bit、linear、weight decay 0.01 | 第二輪學習率 `1e-4`；實際記錄 AdamW 8-bit／linear |
| 硬體紀錄 | T4，訓練約 686 秒，reserved 尖峰 10.049 GiB | RTX 4060 8 GB，第二輪約 62 秒，reserved 尖峰 5.068 GiB |
| 評估 | 影像描述的 BLEU／ROUGE | 工具動作、工具結果等價、完整回答人工檢查 |

兩者任務、硬體、資料和軟體版本均不同，耗時及分數不作模型優劣比較。原專案的顯存紀錄也不應直接套到本機 8 GB GPU。

## 原始碼核對到的問題

下列 cell 編號以 JSON 中從 0 起算的位置為準，皆指固定修訂的[主訓練 notebook](https://github.com/AIOmarRehan/Unsloth_Llama_3.2_11B_Vision_Instruct_Astronomy/blob/6b8d73fbb51c3776b3a2d34064f68481dbf37f0d/Notebook/unsloth_Llama_3_2_11B_Vision_Instruct_Astronomy.ipynb)。這些是來源程式及其保存輸出的核對，並非本機重跑 11B 的結果。

| 發現 | 證據 | 本專案處理 |
| --- | --- | --- |
| 分割結果被覆蓋 | cell 44 切成 200／25／25；cell 45 又從完整 df 重建 hf_dataset；cell 49 用它訓練，cell 52 保存紀錄明列 250 examples；cell 55 再從同一 df 抽評估資料 | 在訓練前固定 ID 與情境群組，檢查跨集合重疊；trainer 實際輸入也逐筆核對 |
| 提示詞進入評分 | cell 56 decode 完整輸出，cell 58 的保存預測含 user 指令；評分長度比約 2.05 | 共用推論以輸入 token 數切出新輸出，已有回歸測試 |
| 清洗破壞訓練目標 | cell 24 的規則只留英文字母與空白，cell 27 覆蓋原始 text | 保留繁體中文、站碼、數字、時刻與標點；體檢不改資料 |
| 沒有 validation loss | cell 49 的 trainer 沒有 eval_dataset | 第二輪已記錄訓練前及 epoch 結束的 validation loss |
| 解碼參數與路徑不一致 | cell 56 沒明寫 do_sample；app.py 使用抽樣並靠字串 assistant 切答案 | 評估與本機入口共用程式，明寫 greedy，依 token 位置切答案 |
| 保存及重載需驗證 | app.py 以 get_peft_model 的 lora_adapter 引數宣稱載入既有權重；沒有保存載入後權重證據 | 我們直接載入已保存 adapter 路徑，檢查 PEFT、非零且有限的 LoRA B、權重雜湊與實際回答 |

本機安裝的 Unsloth 2026.9.7 中，`get_peft_model` 是建立 adapter 的路徑，未見讀取 `lora_adapter` 指定權重的動作。因此該呼叫不可直接作為本機的重載方法；這項核對不代表已重現作者當時版本的實際載入狀態。

此外，[Unsloth 官方文件](https://unsloth.ai/docs/basics/vision-fine-tuning)提供 vision collator 的 response-only 選項；僅看到 collator 被建立，不能證明實際 labels 只訓練 assistant。機捷第二輪已直接核對 87 筆 trainer labels，不依賴這項假設。

## 這次補進機捷專案的內容

新增 `scripts/profile_training.py`，將先前的一次性統計做成可重複執行的資料體檢。它先驗證來源與切分，再統計重複、空訊息、情境群組、工具案例比例、工具狀態及回答字數，保存資料雜湊；不讀取 20 題最終測試，也不清洗或改寫訓練資料。

```powershell
.\.venv\Scripts\python.exe -m scripts.profile_training
```

[實際體檢結果](training_data_profile.json)：

| 項目 | 訓練集 | 驗證集 |
| --- | ---: | ---: |
| 對話 | 70 | 17 |
| 有工具呼叫 | 22（31.43%） | 9（52.94%） |
| 完全重複對話／空文字訊息 | 0／0 | 0／0 |
| 一般查班成功的工具結果 | 14 | 5 |
| 需要釐清車站的工具結果 | 3 | 1 |
| 只剩緩衝時間內末班的工具結果 | 0 | 1 |

ID、情境群組、完整對話內容的跨集合重疊均為 0；這不等於已證明沒有語義相近的例子，也不證明票務等事實全數正確。

**下一輪的具體方向**：檢查工具使用資料比例與邊界情境覆蓋，再處理目的站／列車終點混淆、已知資訊重問等錯誤。「只剩即將發車末班」目前屬於驗證側情境，不能直接搬回訓練；若擴充此類資料，需重新設計並記錄不洩漏的情境切分。

以上資料比例只是可能影響因素，尚未做控制實驗，不能宣稱已找出唯一原因。這次是來源審查與資料體檢，沒有新一輪訓練；第二輪模型及其評估仍保留原紀錄。
