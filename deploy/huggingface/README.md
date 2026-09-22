---
title: 下一站｜機捷 AI 查班助手
emoji: 🚆
colorFrom: blue
colorTo: purple
sdk: gradio
sdk_version: 6.28.0
python_version: 3.12
app_file: app.py
suggested_hardware: zero-a10g
startup_duration_timeout: 1h
pinned: false
---

# 下一站｜機場捷運 AI 查班助手

自行整理班表、訓練 Qwen3 4B LoRA，並製作可直接操作的網頁展示。

- 主畫面保留全線路線圖、深淺主題、中文聊天。
- 使用 RTX 4060 8GB 訓練的第二輪 LoRA adapter，雲端不重新訓練。
- ZeroGPU 使用官方 Qwen3-4B-Instruct-2507 的 BF16 基礎模型，搭配同一份 LoRA；本機為 Unsloth 4-bit，因此模型原始文字不保證逐字相同。
- 班次答案會再經結構化班表核對，保留模型原始輸出作為查詢依據。
- 一般預定班表範圍：2026-09-21 至 2026-10-04；不含特殊活動、即時誤點、票價或轉乘規劃。
- 非官方服務，實際乘車以現場公告為準。ZeroGPU 可能排隊或受訪客 GPU 額度限制。

## 試用

日期設為 **2026-09-22**、時間設為 **10:00**，選 A1 → A13、普通車，預期為 **10:08、10:23**。

也可以直接問：「A12 到 A18，末班車幾點？」預定末班為 **23:58 普通車**。

## 訓練與架構

1. 視覺選站／中文輸入。
2. Gradio 排隊，ZeroGPU 執行 Qwen + 自訓 LoRA。
3. 應用程式依同一組起訖、時間、車種核對班次與停靠站。
4. 呈現班次、來源及接近發車提醒。

詳細資料見 [專案 GitHub](https://github.com/lee851104/tymetro_bot)；部署檔案及 SHA-256 記錄於 `deployment_manifest.json`。

基礎 Qwen 模型遵循 Apache-2.0 授權。模型並未取得桃園捷運官方認證；本專案未提供其他第三方資料的再授權。
