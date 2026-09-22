# 官方資料來源與待補項目

核對日期：2026-09-22。使用者指定一般平假日班表、排除特殊活動；3 分鐘內發車只提醒旅客考慮較晚班次。這兩項屬於本專案政策。

## 結論

官網已有多數票務與站務來源，不需要使用者重新提供或手抄。這次保存 **10 個主題頁＋22 站介紹，共 32 頁**，可重複整理；尚未把網頁全文當作已審核答案。主要缺口是結構化、適用日期、行程串接及即時資料，並非缺更多隨機問答。

## 覆蓋與處理狀態

| 類別 | 已找到的官方來源 | 現況及尚待補齊 |
| --- | --- | --- |
| 班次與平假日 | [桃捷時刻表](https://www.tymetro.com.tw/tymetro-new/tw/_pages/travel-guide/timetable.php)、使用者主表、行政院日曆 | 已可離線查一般班次；班表日期範圍 9/21～10/4，日曆有全年不代表班表全年有效。 |
| 票價與票種 | [單程票與一日票](https://www.tymetro.com.tw/tymetro-new/tw/_pages/travel-guide/ticketson01.php)、[電子票證](https://www.tymetro.com.tw/tymetro-new/tw/_pages/travel-guide/ticketson03.php)、[票價表 PDF](https://www.tymetro.com.tw/tymetro-new/tw/_images/document/travel-guide/price.pdf) | 已保存網頁與 PDF 連結；各站票價矩陣尚未轉錄。頁內同時保存歷年促銷，需核對期間、票卡與資格，不能整頁當現行規則。 |
| 行李、自行車與乘車規則 | [旅客須知](https://www.tymetro.com.tw/tymetro-new/tw/_pages/travel-guide/notice.html) | 已保存條文；要區分未收折自行車、包裝後行李、車種、可搭時段及例外，整理成帶來源的條件資料。 |
| 預辦登機 | [簡介](https://www.tymetro.com.tw/tymetro-new/tw/_pages/checkin/index.html)、[流程](https://www.tymetro.com.tw/tymetro-new/tw/_pages/checkin/process.html)、[桃園機場專頁](https://www.taoyuan-airport.com/ITCI/index.html) | A1／A3 位置與服務時段有來源；航空公司、航班與行李適用性需接續核對機場／航空公司資料，不能只看捷運服務時間就保證可辦理。機場專頁本次純文字讀取未取得正文。 |
| 設施與無障礙 | [無障礙服務](https://www.tymetro.com.tw/tymetro-new/tw/_pages/travel-guide/accessible.html)、各站介紹 | 已保存 22 站文字與平面圖連結；出口／電梯位置仍需依圖核對。設備「有設置」不等於「現在正常運作」。 |
| 轉乘與地標 | [轉乘資訊](https://www.tymetro.com.tw/tymetro-new/tw/_pages/travel-guide/transfer.html)、各站介紹及連結的交通業者 | 已取得來源入口；尚未整合跨業者時刻、步行路徑、行李／輪椅需求及最短轉乘時間，不能提供已驗證的最快方案。 |
| 抵達時間與同列車串接 | [票價與時刻查詢](https://www.tymetro.com.tw/tymetro-new/tw/_pages/travel-guide/timetable-search.html) | 官方有查詢入口，但本次程式提交 A3→A10 只取得輸入頁，未解析出可靠的行程結果。現有各站發車表尚無已驗證的同列車識別；不能用相近分鐘直接配對。這是目前整合缺口，不能據此宣稱官網沒有資料。 |
| 遺失物與協助 | [遺失物](https://www.tymetro.com.tw/tymetro-new/tw/_pages/service/lost.html)、[常見問題](https://www.tymetro.com.tw/tymetro-new/tw/_pages/service/FAQ.html) | 官方查詢管道、服務時間可整理；個別遺失物狀態不應寫成固定訓練答案。 |
| 即時異常 | 官方公告、現場看板與站務確認 | 尚未串接能確認即時延誤、臨時停駛及電梯故障的來源；靜態時刻表不能證明目前正常。 |

## 這次實作與驗證

- 依使用者修改接入 22 站暱稱；刪除「新產」，保留必要的地區、航廈及地標追問，C15 不採用。
- 距查詢時間 3 分鐘內（含邊界）的車次不列為建議班次；末班情況另處理。原始班表時間未改動。
- 新增 12 題暱稱、追問、邊界與安全提醒案例，合計 87 筆：70 訓練、17 驗證。20 題最終測試未動。
- 本次資料整理階段 57 項程式測試通過，tokenizer 檢查 87 筆、120 段 assistant，最長 960／1,024 tokens。後續已完成第二輪訓練並增至 61 項測試，見[第二輪結果](training_round2.md)；本頁的 32 頁官方原始內容仍未整批加入訓練。

## 資料格式與重建

`data/knowledge/official_sources.json` 保存各頁 `id`、`url`、`fetched_at`、`sha256`、標題、正文、連結及圖片網址。原始 HTML 保存在已忽略的 `outputs/knowledge_raw/`。所有原始頁面目前 `answer_ready=false`，表示尚未逐條整理為可供回答的規則。

```powershell
.\.venv\Scripts\python.exe -m scripts.fetch_official_knowledge
# 重新向官網取得修訂內容時才加 --refresh
```

正式規則應包含：問題類型、適用站點／票種／對象、條件、例外、生效與失效日期、來源與核對日期。未知日期留空並標示狀態，不把下載日期當作生效日。票價、班次及會變動的規則適合保存在可更新的知識資料；SFT 教模型追問和使用資料。

## 仍適合使用者審查的內容

現場常見說法、回答是否自然、旅客容易搞混的情況，以及官網未列出的經驗情境。官網能取得的金額、條文、設施及服務時間由程式整理，不要求使用者再抄一次。32 題回答範例尚未視為全部確認。

另查到飯店名稱需保留更新紀錄：你在 C08 寫的「諾富特」可保留作旅客用語背景；目前[飯店官方頁面](https://www.hyatt.com/hyatt-regency/zh-HK/tpera-hyatt-regency-taoyuan-international-airport)使用「桃園國際機場凱悅酒店」，地址為航站南路 1-1 號。不可把舊品牌永遠寫作現行名稱；完整飯店名到車站／出口的映射仍需核對交通頁。
