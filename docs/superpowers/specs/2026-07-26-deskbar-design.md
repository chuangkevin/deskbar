# deskbar — Raspberry Pi 桌面行事曆儀表板 設計文件

- 日期：2026-07-26
- 狀態：設計已與使用者逐項確認，待最終審查
- 硬體：Raspberry Pi Zero 2 W（512MB RAM）＋ 8.8 吋 1920×480 觸控長條屏（HDMI，面板原生 480×1920 直向）

## 1. 目標與範圍

在桌面長條屏上 24 小時顯示多個 Google 帳號的當日行程時間軸與時間/天氣資訊，支援觸控查看行程詳情與帳號日曆開關。

**範圍內**：多帳號 Google Calendar 唯讀同步、泳道式時間軸、天氣、觸控基本互動、開機自動全螢幕啟動、離線快取。

**範圍外**（明確不做）：DAKboard／瀏覽器 kiosk、Pi 上瀏覽器登入、行程新增/編輯（唯讀）、翻頁鐘動畫（留待後續迭代）、拖曳時間軸等重度互動、5GHz Wi-Fi。

## 2. 關鍵決策記錄

| 決策點 | 選擇 | 理由 |
|---|---|---|
| 實作路線 | Python + Pygame 自製 UI（方案 B） | 512MB RAM 跑 Chromium 不穩；21:9 版面需完全自訂 |
| 執行環境 | 已燒含桌面版 Raspberry Pi OS 64-bit，設定開機進文字模式，Pygame 走 SDL KMSDRM 直畫 framebuffer | 不載桌面省 RAM（目標整機 <200MB）；免重燒 |
| Google 授權 | OAuth 桌面流程在 **Mac 上執行**（授權精靈），refresh token 部署到 Pi | Google 裝置流程（QR/TV）白名單不含 Calendar scope；Pi 上跑瀏覽器不可行；2FA/passkey 在 Mac 瀏覽器照常運作 |
| 帳號模型 | 多帳號，每帳號一個 token 檔，Pi 每同步週期重掃帳號目錄 | 新增帳號免重啟；單帳號失效不影響其他帳號 |
| 日曆資料 | Google Calendar API `calendar.readonly`，每 5 分鐘輪詢 | 近即時；唯讀最小權限 |
| GCP 同意畫面 | External ＋ **發布為正式版**（不驗證） | 測試模式 refresh token 七天過期，發布後長期有效；「未驗證應用程式」警告為個人自用預期行為 |
| 天氣 | Open-Meteo（免 API key），預設台北市中心範例座標，每 30 分鐘更新 | 免申請、免保管金鑰；地點為設定值可改 |
| 螢幕旋轉 | 應用內以 1920×480 邏輯座標作畫，輸出前旋轉 90° 到面板原生 480×1920；觸控座標做同一旋轉的反向轉換 | KMS 下最單純可控；方向（90°/270°）為設定值，點亮時實測定案 |
| 觸控範圍 | 基本互動：點行程看詳情、點齒輪進設定 | 使用者確認；重度互動不做 |
| 公司/私人區分 | 時間軸依帳號切**獨立泳道**，左緣色條＋可自訂短標籤（如「工作」「個人」） | 使用者要求一眼可分公私行程；色點圖例不夠明確 |

## 3. 系統架構

### Pi 端：單一 Python 程序（`deskbar`）

三執行緒，程序內以 thread-safe 的狀態儲存（store）溝通，UI 每幀讀取快照：

- **UI 主執行緒**：Pygame 事件迴圈與渲染。狀態變化或每秒整點才重繪（時鐘秒針），平時 idle；重繪成本含 90° 旋轉貼圖，預估每次 15–25ms，CPU 平均佔用個位數百分比。
- **日曆同步執行緒**：每 5 分鐘掃描帳號目錄 → 對每個帳號用其 refresh token 換 access token → 拉取該帳號已啟用日曆的「當日＋整日」行程 → 正規化後寫入 store 與磁碟快取。
- **天氣同步執行緒**：每 30 分鐘拉 Open-Meteo 目前天氣＋當日高低溫，寫入 store 與磁碟快取。

### Mac 端：開發與授權工具（同 repo）

- `make add-account`：開瀏覽器跑 Google OAuth（localhost redirect），完成後把該帳號 token JSON `scp` 到 Pi 帳號目錄。加帳號唯一入口。
- `make deploy`：rsync 程式碼到 Pi ＋ 重啟 systemd 服務。
- `make dev`：Mac 上開 1920×480 視窗跑同一套 UI（SDL 視窗模式），開發不用碰 Pi。

### 目錄結構

```
deskbar/
├── deskbar/                 # Pi 端應用（Mac dev 模式共用）
│   ├── __main__.py        # 進入點與主迴圈
│   ├── config.py          # settings 載入/儲存
│   ├── accounts.py        # 帳號目錄掃描與各帳號狀態
│   ├── gcal.py            # Google Calendar API 用戶端（唯讀）
│   ├── weather.py         # Open-Meteo 用戶端
│   ├── store.py           # thread-safe 應用狀態＋磁碟快取
│   ├── sync.py            # 兩條背景同步執行緒
│   └── ui/
│       ├── app.py         # Pygame 初始化、KMSDRM/視窗、旋轉輸出、事件分派
│       ├── theme.py       # 顏色/字型/尺寸常數（深色主題）
│       ├── dashboard.py   # 左側面板＋主畫面組裝
│       ├── timeline.py    # 泳道佈局引擎（純函數，可單元測試）
│       ├── settings_view.py # 設定頁（帳號/日曆開關/泳道改名/移除帳號）
│       └── touch.py       # 觸控座標旋轉轉換＋命中測試
├── tools/add_account.py   # Mac 授權精靈
├── deploy/                # deskbar.service、install.sh、開機設定片段
├── tests/                 # pytest（Mac 上跑）
├── Makefile
└── docs/superpowers/specs/
```

### Pi 上的資料位置

- `~/.config/deskbar/settings.json` — 顯示設定（各帳號啟用日曆、泳道標籤與顏色、天氣座標、旋轉方向、時間軸起訖）
- `~/.config/deskbar/client_secret.json` — GCP 桌面型 OAuth client（chmod 600）
- `~/.config/deskbar/accounts/<email>.json` — 各帳號 refresh token（chmod 600）
- `~/.cache/deskbar/events.json`、`weather.json` — 離線快取（含抓取時間戳）

## 4. UI 設計（1920×480，深色主題）

### 主畫面

- **左側面板（0–480px）**：大字時鐘（HH:MM，等寬數字）、日期與星期、天氣（圖示＋現溫＋地點＋當日高低溫）、左下同步狀態（點＋「已同步 N 分鐘前」）、右下齒輪（觸控目標 ≥48px）。
- **右側時間軸（480–1920px）**：
  - 頂部細條：整日行程 chips，依帳號上色，多日事件跨越的每一天都顯示。
  - 主體：**每個啟用帳號一條泳道**，垂直均分，左緣 3px 帳號色條＋短標籤；帳號內行程重疊時泳道內再分子車道。最多支援 4 個啟用帳號的可讀排版。
  - 時間軸固定顯示「當前日期」的 08:00–24:00，每 2 小時一條淡格線與軸標籤；**現在線**（橘色豎線＋時間泡泡）每分鐘更新，只在 08–24 區間顯示（凌晨時段自然顯示新一天的行程、無現在線）。
  - 跨界事件：07:00–09:00 這類跨起點的行程裁切到 08:00 起畫並帶「◀」記號；跨 24:00 同理帶「▶」。
- **字型**：Noto Sans CJK TC（Pi 需安裝 `fonts-noto-cjk`），行程標題中文為主。

### 觸控互動

- 點行程塊 → 詳情浮層（完整標題、時間、地點、說明前幾行），點浮層外關閉。
- 點齒輪 → 設定頁。
- 觸控座標經與顯示相同的旋轉矩陣反向轉換，點哪是哪。

### 設定頁

- 每帳號一張卡：色點＋帳號名、泳道標籤改名（點標籤在預設清單間循環：工作／個人／家庭／帳號名；不做裝置上自由輸入，特殊名稱可 SSH 改 settings.json）、該帳號各日曆的顯示開關、「移除帳號」（二次確認；刪 token 檔）。
- **「旋轉螢幕」按鈕**：點擊立即在 90°／270° 間切換（畫面翻面＋觸控矩陣同步反轉），免重開機，寫入 settings.json。使用者可能隨時改變螢幕擺放方向，此為常用操作。
- 「新增帳號」卡顯示引導文字：「在 Mac 執行 make add-account」。
- 「完成」返回主畫面；變更即時生效並寫入 `settings.json`。

## 5. 資料層

- **行程正規化**：各帳號各日曆的 events 統一為 `{id, account, calendar_id, title, start, end, all_day, location, description}`；時區一律轉 `Asia/Taipei`（系統時區）。
- **輪詢**：`events.list(timeMin=今日00:00, timeMax=明日00:00, singleEvents=true, orderBy=startTime)`；每帳號每日曆一次請求，配額遠低於上限。
- **快取**：每次成功同步覆寫磁碟快取；開機或斷網時以快取渲染，並在同步狀態顯示資料年齡。
- **天氣**：Open-Meteo current ＋ daily high/low，座標存於裝置上的 settings.json（範例值 25.046, 121.517；實際地點不入 repo）。

## 6. 顯示管線與開機設定

- SDL 後端：Pi 上 `SDL_VIDEODRIVER=kmsdrm`（Bookworm 的 SDL2 支援）；Mac dev 模式為一般視窗。
- 若面板 EDID 不被正確識別，於 `cmdline.txt` 以 `video=HDMI-A-1:480x1920@60` 強制模式；文字主控台加 `fbcon=rotate:1` 讓 log 可讀。
- 防休眠：`cmdline.txt` 加 `consoleblank=0`；無 X/桌面故無 DPMS/xset 需求。
- 開機流程：`raspi-config` 設 boot to CLI（不自動登入桌面）→ `deskbar.service`（systemd，`After=network-online.target`、`Restart=always`、以一般使用者執行，加入 `render`/`input` 群組）啟動應用。

## 7. 錯誤處理與韌性

| 情境 | 行為 |
|---|---|
| 斷網 | 以快取渲染；同步狀態顯示「上次同步 N 分前」轉黃/紅 |
| 單一帳號 token 失效/被撤銷 | 該帳號泳道標示警告圖示與「需重新授權」，其他帳號照常 |
| Google API 錯誤/限流 | 指數退避重試；不阻塞 UI |
| 開機尚未對時（無 RTC） | NTP 同步完成前顯示「時間未同步」、不畫現在線 |
| 程式崩潰 | systemd 自動重啟；journald 收 log |
| 天氣 API 失敗 | 顯示快取值與資料年齡；連續失敗顯示「—」 |

## 8. 安全

- 僅 `calendar.readonly` scope；token 與 client secret 檔案權限 600；SSH 僅金鑰登入。
- repo 可公開：`client_secret.json`、`accounts/`、`settings.json`、快取一律 gitignore；範例檔以 `*.example` 提供；不含任何公司識別資訊。

## 9. 測試策略

- **pytest（Mac）**：泳道佈局引擎（重疊分車道、裁切、多帳號分道）、時間↔像素換算、觸控旋轉轉換矩陣、行程正規化（整日/跨日/時區）。
- **Mac dev 視窗**：以假資料與真帳號各跑一輪視覺驗證。
- **Pi 煙霧測試**：服務啟動、旋轉方向正確、觸控命中、斷網拔網線驗證快取路徑、重開機自啟。
- **驗收清單**：交接手冊 Step 1–4 全數完成＋觸控互動與多帳號泳道如 mockup。

## 10. v2 追加功能（使用者決定併入本輪實作）

### 10.1 鬧鐘系統
- **儲存**：`~/.config/deskbar/alarms.json`，欄位 `{id, time:"HH:MM", days:[0-6]（Python weekday，空陣列＝一次性）, label, enabled}`；`AlarmStore` 類別持鎖，web 執行緒與 UI 執行緒共用。
- **觸發**：UI 主迴圈每秒查 `due_alarms(last_check, now)`；到點→全螢幕閃爍覆疊（珊瑚色/深色 2Hz 交替）＋鬧鐘標籤＋時間；**點任意處關閉**；一次性鬧鐘觸發後自動停用並存檔，重複鬧鐘清除當次狀態。
- **打卡情境**：週一到五重複鬧鐘（days=[0,1,2,3,4]）。

### 10.2 Web 設定介面
- Pi 起 Flask 執行緒（port 8080，`0.0.0.0`），任何 tailnet/區網裝置開 `http://rpi2w:8080` 即可管理鬧鐘（新增/啟停/刪除），單頁 HTML＋fetch API，無登入（tailnet 即信任邊界）。
- API：`GET/POST /api/alarms`、`PATCH/DELETE /api/alarms/<id>`。
- RAM 預算：Flask 執行緒 +15~20MB，總預算 <200MB 不變。

### 10.3 翻頁時鐘動畫
- 左面板大時鐘升級為翻頁卡片式：分鐘變化時播放約 400ms 的翻板動畫（動畫期間暫時提高重繪頻率，平時維持低頻省電）。

## 11. v4 追加功能（時間軸大改版）

- **強制同步**：主畫面左下同步狀態為觸控目標，點擊立即觸發一輪日曆＋天氣同步；同步進行中顯示「同步中…」。
- **同步頻率**：settings 新增 `sync_interval_min`（預設 5），設定頁可在 1/3/5/10/30 分鐘間調整，同步執行緒即時生效。
- **資料窗口**：同步一次抓「今天−7 天 … 今天＋30 天」全窗口行程，所有視圖與滑動皆從本地窗口渲染；平移範圍以此為界。
- **顯示寬度**（右上切換鈕循環）：半天（錨點−2h…+10h）／日（08–24，預設）／週（錨點週的一～日連續軸，事件塊免標籤、點擊看詳情）／月（每日×每帳號「件數格」，點格跳該日日視圖）。
- **滑動平移**：時間軸區域拖曳 = 平移錨點（位移超過 24px 判定為拖曳而非點擊）；偏離「現在」時顯示「回今天」鈕。
- **顯示模式**：河道（現行泳道）↔ 行程（時間排序卡片清單，帳號色邊，點卡看詳情），右上第二顆鈕切換，設定持久化。

## 12. 一次性人工步驟（使用者操作，我逐步指引）

1. ✅ Raspberry Pi Imager：主機名/帳號/2.4G Wi-Fi/SSH 公鑰已設定燒錄。
2. GCP Console：建專案 → 啟用 Google Calendar API → OAuth 同意畫面（External、加 `calendar.readonly` scope、**發布正式版**）→ 建「桌面應用程式」OAuth client → 下載 `client_secret.json` 交給專案。
3. 每個要顯示的 Google 帳號在 Mac 上跑一次 `make add-account`（含公司帳號；登入時的「未驗證應用程式」警告點「進階→繼續」）。
