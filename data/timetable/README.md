# 一般平假日班表與官方來源

來源：[桃捷各站時刻表](https://www.tymetro.com.tw/tymetro-new/tw/_pages/travel-guide/timetable.php)。

本目錄的 `cache.json` 是依使用者確認的 **一般班表**，平假日採行政院 115 年辦公日曆，**不納入特殊活動**。官網原始逐日快取另存 `official_cache.json`，含活動資料供追查。旅客詢問時只讀本機，不重新下載。完整時刻表不放入 LoRA；訓練案例由工具查出需要的少量班次。

目前一般班表涵蓋 **2026-09-21～2026-10-04，全線 22 站**：308 份站別日期資料、37 種模式、51,916 筆各站發車紀錄（同一列車在不同站分別計算）。平日參考 2026/9/21 官網班表，假日參考 2026/10/17 無活動調整的官網班表；使用者圖片轉錄已分別核對。每個日期保存 `day_type` 與 `reference_service_date`，不把基準日內容冒充該日官網實際班表。更新後範圍以 `calendar` 為準。

`calendar_2026.json` 包含全年 365 日、120 個放假日。來源 PDF 第 1 頁以顏色標上班／放假；第 2 頁紀念日不一律放假。日曆判定範圍與班表有效範圍獨立，未提供日曆的年份不自動套用週末規則。原始下載統計保存在 [歷史下載報告](../../reports/timetable_cache.md)。

## 查詢

只需 Python 3.11 以上與標準函式庫。在專案根目錄執行：

```powershell
python -m scripts.query_timetable --origin A8 --destination A10 --at "2026-09-21T10:00:00+08:00" --format text
```

- 起訖站可填代碼、正式站名或已審核暱稱，例如 `--origin 長庚林口 --destination 一航`。程式依站序判斷方向，支援 A14a、臺／台字形及省略末尾「站」。暱稱來源為 `data/station_aliases.json`；新莊、青埔等不明確地點及站碼／站名衝突時要求釐清，不用模糊比對猜站名。
- 上例回傳 10:08、10:23 普通車；10:07 直達車不停 A10，因此排除。篩選在取最近兩班之前完成。
- 若只要看方向，可改用 `--station A8 --direction down`。`--destination` 與 `--direction` 擇一。
- 起訖查詢預設保留超過 3 分鐘才發車的班次；3 分鐘內（含邊界）另列 `imminent_departures`，提醒勿趕車。方向查詢用於檢視原始班表，不套用此建議緩衝。時間以查詢時間為基準；並非各站實測進站時間，也不保證搭得上。
- `up` 是北上（往台北方向），`down` 是南下（往機場／中壢方向），輸出同時保留官網的方向文字。A1、A22 等端點的其中一個方向可能沒有班次。
- `--at` 可省略，預設臺灣現在時間；指定時必須帶時區。`--limit` 預設 2。
- 預設輸出 JSON，`--format text` 可輸出繁體中文說明。
- 起訖站程式介面是 `src.timetable.query_direct_trains(origin, destination, query_time)`；方向介面是 `src.timetable.query_departures(station_id, direction, query_time)`。
- 輸出含發車日期時間、車種、停靠規則文字、基準頁擷取時間、來源與一般班表政策。另含 `day_type`、`special_events_included=false`、`reference_service_date`、行政院日曆來源。
- 起訖查詢另含 `destination_id`、`direct_only=true`，各班次附終點與 `stops_to_destination`。`arrival=null` 明確表示尚無抵達時間。
- `date_not_cached` 表示沒有建置該日班表，不代表停駛；查詢過程不自行展開日期。建置指令才會依已核對的日曆與基準班表產生指定範圍。
- `no_departures_remaining` 表示該營運日／方向的預定班次已用完，不表示目前路線停駛。
- `no_direct_departures_remaining` 表示已無後續不需換車到目的站的班次，仍可能有尚未計算的轉乘選項。
- `only_imminent_departures_remaining` 表示只剩緩衝時間內的班次，沒有更晚的符合條件班次，不能繼續建議不存在的下一班。
- `service_rules_unavailable` 表示圖例、停靠規則或活動日期需要重新核對，不會把未知車種一律當作普通車。

這台 Windows 電腦若 `python` 指令找不到，可使用已安裝的完整路徑：

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe" -X utf8 -m scripts.query_timetable --origin A8 --destination A10 --at "2026-09-21T10:00:00+08:00" --format text
```

## 更新

### 使用者提供的 2026/9/21 圖片

已保存 [原圖](sources/time_2026-09-21.jpg) 與 [結構化轉錄](sources/time_2026-09-21.json)。使用者已確認全部四項問題：07:00 跳站車以主表為準、假日 A18 13:54、不納入特殊活動、南下 22:00 後 A10～A17 慢 2 分鐘。平日 759 項及假日 627 項，共 1,386 項檢查通過。詳見 [圖片核對報告](../../reports/timetable_image_review.md)。

執行 `.venv\Scripts\python.exe -m scripts.audit_timetable_image` 可重跑此份圖片的核對。比對會分開處理到站／發車、跨午夜與特殊車種；不在已含夜間調整的快取上重複加分鐘。

### 官網下載

```powershell
python -m scripts.fetch_timetable --start 2026-09-21 --days 14
```

省略 `--start` 時從臺灣今天起算；預設抓 14 天、全線 22 站（包含 A14a）。抓取逐筆進行，請求間隔預設 0.4 秒，網路錯誤最多重試 3 次。只有完整一天的所有車站均通過檢查，才更新快取檔案。

中斷後重跑會重用 `outputs/timetable_raw/` 下已校驗的原始頁面。若要取得官網後續修訂，務必加上 `--refresh`：

```powershell
python -m scripts.fetch_timetable --start 2026-09-21 --days 14 --refresh
```

下載預設寫入 `official_cache.json`，舊日期保留供追查；若指定覆蓋已建置的政策快取，程式會拒絕。原始 HTML 在已忽略的 `outputs/` 下。一般假日基準另存 `sources/official_holiday_2026-10-17.json`。沒有設定背景排程。

### 建置一般班表

```powershell
python -m scripts.build_normal_timetable --start 2026-09-21 --days 14
python -m scripts.audit_timetable_image
python -m scripts.prepare_training
```

建置會驗證行政院來源 PDF 雜湊、基準日所有車站及模式完整性，拒絕含活動車種的基準、缺少日曆的日期、9/21 以前或超過基準頁公布期限（10/31）的日期。`--days` 可指定需建置的範圍，並完整重建 `cache.json`。22:00 後 A10～A17 的慢行已包含在逐站基準時刻，不再加一次分鐘。

官網日期選擇功能先 POST 至 `station-timetable-date.php`，再以 `tymetro_new_chdate` Cookie 讀取各站頁面。實測 Cookie 只有 10 秒有效，下載器因此逐次帶入指定日期，並檢查回應頁面的日期與車站。網頁日期選擇器的最遠日期可能超出實際公布班表範圍；下載器以正文的「目前時刻表更新至」為上限。

## JSON 結構

| 欄位 | 用途 |
| --- | --- |
| `schema_version` | 結構版本，目前為 1 |
| `source_type` | 固定為 `scheduled`，表示預定班表 |
| `stations` | 站代碼與站名 |
| `calendar[日期][車站]` | 該營運日所用班表、平假日、基準日期與頁面雜湊、日曆來源、排除特殊活動的政策 |
| `patterns[SHA256]` | 去除重複後的車站班表；相同日期內容只存一份 |
| `patterns[…].directions.up/down` | 方向文字、發車清單及原始車種說明 |
| `departures[].time` | `HH:MM` 的預定發車時間 |
| `departures[].day_offset` | 0 為該營運日，1 為隔天凌晨 |
| `departures[].service_code` | 官網樣式代碼，搭配 `legends` 查車種及停靠說明 |

時間表列順序為 05 時至隔日 01 時；本程式把 00、01 時列算作營運日的隔天，查詢使用凌晨 03:00 作為營運日分界。此處保留這項解讀，日後若來源加入服務日或車次欄位，應改以該欄位核對。

解析時會比對網頁報讀版與視覺版的兩份班表，避免重複計算；日期錯誤、缺少時段、未知車種、兩版本時間不一致時會停止，不把錯誤網頁當作無車。

## 使用範圍

此快取提供「某站往某方向」及「起站到目的站、不需換車」的預定最近班次。`service_rules.json` 保留官網七種車種的規則供來源核對；目前一般班表只用 des01～des05，活動車種 des06／des07 不進入查詢。一般每站停靠依全線站序解讀，特殊終點依各標記處理。這是依圖例做的停靠判斷，並非車次逐站時刻資料。

查詢前會核對快取的圖例文字與已審核規則，並核對活動日期。站點或圖例變動時停止提供起訖建議，待更新規則後再使用。活動區間普通車只在 A12～A21 行駛；往機場加班車南下至 A13、北上至 A12，不能因為是普通車就推薦到全線任一站。

官網三角標記的總圖例寫 A22→A12，但逐格報讀文字仍寫 A21→A12。規則保留此差異，使用總圖例與 A22 實際列出的班次；兩處北上終點都是 A12。所有原始圖例及逐格說明仍保留供追查。

官網各站表未提供本程式可可靠串接的車次識別與抵達時間，因此目前不會用兩站相近的時刻猜同一班車，也不提供最快轉乘或目的站抵達時間。既有 `src/schedule.py` 仍是模擬路徑選擇器；這份快取使用獨立的離線發車查詢介面。

這份資料不含即時延誤或臨時停駛；查詢回傳 `service_status=unknown`、`live_disruptions_checked=false`，避免把預定班表當作現場營運正常的證據。預定班表依適用日期使用，不套用模擬即時資料的 15 分鐘過期門檻。
