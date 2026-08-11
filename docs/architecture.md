# deskbar 架構筆記

> 這份文件是給要改程式的人看的模組地圖，不重複產品規格（規格見
> [`docs/superpowers/specs/2026-07-26-deskbar-design.md`](superpowers/specs/2026-07-26-deskbar-design.md)）。
> 隨模組增減會過時，發現不一致以程式碼為準，並請一併更新這份文件。

## 1. 模組職責一覽

### `deskbar/`（核心，Pi 上跑，Mac dev 模式共用同一套）

| 檔案 | 職責 |
|---|---|
| `__main__.py` | 進入點：載入 settings、建立 `AppState`、啟動同步/web/在場感應等背景執行緒、組出 `App` 並 `run()`（Claude usage 沒有背景執行緒，改由 `webserver.py` 的 `/api/usage` 被動接收 Mac agent 推送） |
| `config.py` | `Settings`/`AccountCfg` dataclass（含 `theme:str="dark"`，載入時驗證非 `dark`/`light` 回退 `dark`）與 `settings.json` 載入/儲存（原子寫入）；`config_dir()`/`cache_dir()`/`accounts_dir()` 路徑解析（吃 `DESKBAR_CONFIG_DIR`/`DESKBAR_CACHE_DIR` 環境變數，供測試隔離） |
| `store.py` | `AppState`：執行緒安全的應用狀態（事件、天氣、帳號同步狀態、在場狀態、Claude usage），`snapshot()` 給 UI 讀、依 `seq` 做零成本快取；`save_cache()`/`load_cache()` 落地事件快取（原子寫入） |
| `alarms.py` | `AlarmStore`：鬧鐘 CRUD、`due()` 到點判斷（一次性自動停用）、`alarms.json` 原子讀寫 |
| `sync.py` | 兩條背景同步的實作：`calendar_sync_once`（三階段：鎖內快照設定→鎖外網路 I/O→寫回 state）、`weather_sync_once`；`start_threads()` 起 `cal_loop`/`wx_loop`，`request_sync()` 觸發強制同步 |
| `auth.py` | Google OAuth：`load_accounts()` 掃帳號目錄、`get_access_token()` 用 refresh_token 換 access_token（含記憶體快取與過期判斷） |
| `gcal.py` | Google Calendar API 唯讀用戶端：`fetch_range_events()` 依窗口抓事件 |
| `weather.py` | Open-Meteo 用戶端：`fetch_weather()`、`code_text()` 天氣代碼轉文字 |
| `models.py` | `Event` dataclass；`normalize_event()` 正規化原始 API 回應（HTML 清洗、時區轉換、整日/跨日判斷）；`event_to_json`/`event_from_json` 供快取序列化 |
| `layout.py` | 泳道佈局純函數：事件重疊分子車道、時間↔像素座標換算（`Rect`/`Placed`） |
| `viewwin.py` | 顯示窗口純函數：依 `span`（half/day/week/month）與錨點算 `view_window()`/`agenda_window()`；`clamp_anchor()` 限制平移範圍在資料窗口內；`next_span()`、`window_label()` |
| `transform.py` | 螢幕旋轉角度對照、`touch_to_logical()` 觸控座標反解（原生 480×1920 → 邏輯 1920×480） |
| `presence.py` | 藍牙在場感應（可選功能）：`probe_once()` 用 `l2ping`/`hcitool` 探測、`decide()` 純函數狀態機（含防抖寬限）、`start_presence_thread()` |
| `claudeusage.py` | Claude Code usage 純資料層：`UsageInfo` dataclass 與 `fmt_countdown()` 倒數格式化純函數；不做任何網路呼叫或 OAuth（裝置端自行登入這條路已驗證會被 Cloudflare/限流擋下，改由 Mac agent 推送，見下） |
| `webserver.py` | Flask app：`/` 手機網頁、`/api/alarms` CRUD、`/api/calendars` 日曆開關、`POST /api/usage` 被動接收 Mac agent 推送的 Claude usage（選填 `DESKBAR_PUSH_TOKEN` 環境變數做簡單保護）；`start_web()` 起背景執行緒（`0.0.0.0:8080`） |

### `deskbar/ui/`（Pygame 渲染與觸控分派）

| 檔案 | 職責 |
|---|---|
| `app.py` | `App` 主迴圈：初始化顯示（KMSDRM/視窗）、事件迴圈、觸控座標轉換與拖曳判定、`_dispatch()` 動作分派、旋轉輸出 `_flip()`、切換過場動畫、翻頁時鐘節奏控制 |
| `__init__.py` | `Hit` dataclass（觸控命中矩形＋動作名＋附帶資料），各渲染模組回傳的 hit 清單共用型別 |
| `theme.py` | 雙主題色板系統：`PALETTES={"dark","light"}`、`set_theme()`/`current_theme()` 切換（`C`/`ACCOUNT_COLORS` 模組級容器 in-place 更新，`from-import` 舊引用不受影響）、`register_cache_clear()` 供其他模組登記主題切換時要清空的顏色快取；`col()` 支援 `DESKBAR_BGR=1` 面板色序反轉（在 `set_theme()` 內套用）；`font()`/`truncate_to_width()`/`wrap_lines()` |
| `dashboard.py` | 主畫面組裝：左面板（時鐘/天氣/同步狀態）＋右側時間軸，依 `settings.view_mode` 分派到河道（`_render_lanes`/`weekgrid`/`monthgrid`）或行程（`agenda`）渲染，頂欄寬度切換與窗口標籤 |
| `weekgrid.py` | 河道模式的週檔：帳號×日格子，每格微列事件 |
| `monthgrid.py` | 河道模式的月檔：每日表頭＋每帳號件數膠囊，點格跳日視圖 |
| `agenda.py` | 行程模式：一天一塊直欄（day/half 單欄、week/month 七欄並排） |
| `detail.py` | 行程詳情浮層、整日事件清單浮層 |
| `settings_view.py` | 設定頁：帳號卡（日曆開關/泳道標籤/移除帳號）、旋轉按鈕、主題切換鈕（深色/淺色）、QR code、同步頻率 |
| `alarm_view.py` | 裝置端鬧鐘管理頁（清單＋新增面板） |
| `alarm_overlay.py` | 鬧鐘觸發時的全螢幕閃爍覆疊 |
| `flipclock.py` | 翻頁式時鐘卡片渲染與動畫 |
| `weatherfx.py` | 左面板天氣氛圍背景層（低幀率視覺效果，不影響互動） |
| `scenes.py` | 十個氛圍場景的選擇、輪播、裁切與 renderer lifecycle；各 `scene_*.py` renderer 僅持有目前場景素材 |
| `scene_runtime.py` | `SceneFrame`、renderer Protocol 與 close/decoded-byte contract |
| `scene_assets.py` | 單一 active renderer 的 lazy PNG、混光、染色/縮放快取與 48 MiB 上限 |
| `icons.py` | 向量圖示（齒輪等，避免依賴字型檔不一定有的符號字形） |
| `qr.py` | 設定頁 QR code 繪製（純 Python `qrcode`，不依賴 Pillow） |
| `usagewidget.py` | 右欄 Claude Code 用量油表（三組進度條，純資訊顯示） |

### `tools/`（Mac 端工具，不隨 deskbar 主程式部署到 Pi）

| 檔案 | 職責 |
|---|---|
| `add_account.py` | Google OAuth 桌面流程精靈：本機開瀏覽器授權，完成後把 token JSON 部署到 Pi 帳號目錄 |
| `render_matrix.py` | 渲染驗證矩陣：載入真實/假資料，把顯示寬度×模式×錨點全排列存成 PNG，供人眼核對版面；`--theme dark\|light\|both` 切換輸出色板（`both` 額外對 6 張代表圖各補一張 `_light` 版本） |
| `gen_scene_assets.py` | 依固定順序呼叫 `scene_bakers/`，重建全部 1240×472 場景素材 |
| `render_scene_review.py` | 產生十場景晨/晝/夜、0/5/15 秒 motion、contact sheet 與 metrics JSON |
| `benchmark_scenes.py` | 每場景 20 warm-up＋120 measured 的 median/p95/max、decoded bytes、RSS 報告 |
| `usage_push_snippet.py` | 可直接複製貼進既有 usage agent（例如 claude-usage-cube/agent/cube_agent.py）的 `push_to_deskbar()` 函數，把讀好的 usage POST 給 `/api/usage` |
| `usage_push_demo.py` | 獨立小工具：讀本機 Keychain 的 Claude Code 憑證、打官方 usage API、POST 到 deskbar，不想改既有 agent 時單獨用 |

## 2. 資料流

```
Google Calendar API ──┐                      Open-Meteo API
                       │                              │
                 gcal.fetch_range_events        weather.fetch_weather
                       │                              │
                 models.normalize_event               │
                       │                              │
                       ▼                              ▼
              sync.calendar_sync_once ──────► store.AppState ◄────── sync.weather_sync_once
                       │                       (lock + seq,           │
                       │                        snapshot 快取)        │
                       ▼                              │                └─ 失敗只印 stderr，
              store.save_cache()                      │                   保留舊值不中斷
              （原子寫入 events.json）                  │
                                                       ▼
                                          ui.app.App._render()
                                          （每格讀一次 snapshot()）
                                                       │
                                    ┌──────────────────┼───────────────────┐
                                    ▼                  ▼                   ▼
                          ui.dashboard.render   ui.settings_view    ui.alarm_view /
                          （河道 / 行程 / 頂欄）   （帳號/旋轉/QR）    alarm_overlay
                                    │
                                    ▼
                          transform + pygame 旋轉輸出 → framebuffer（或 dev 視窗）

手機/平板 ──HTTP──► webserver.py(Flask) ──► alarms.AlarmStore ──► alarms.json（原子寫入）
                                        └──► config.Settings（日曆開關，經 settings_lock）
```

要點：

- **UI 只讀 snapshot，不直接碰網路或磁碟**——同步/天氣/在場/用量都是背景執行緒把結果寫進 `AppState`，UI 主迴圈每幀 `state.snapshot()` 拿一份不可變快照渲染，兩邊靠 `AppState._lock` 與 `seq` 遞增解耦。
- **設定（`Settings`）走另一把鎖**（`settings_lock`，`App.lock`）：UI 觸控分派、`sync.py` 的階段 (a)、`webserver.py` 的日曆開關 API 都會短暫持有它；規則是「只在讀寫純量/小字典時持鎖，網路 I/O 一律搬到鎖外」，避免長時間凍結觸控。
- **落地檔案一律原子寫入**（`config.save_settings`、`alarms._save_locked`、`store.save_cache`）：`tempfile.mkstemp` 在目標同目錄開暫存檔寫完整內容，成功才 `os.replace()` 蓋過正式檔名，避免寫到一半斷電/例外留下半截 JSON。

## 3. 執行緒清單

| 執行緒 | 建立位置 | 週期 / 觸發 | 鎖規則 |
|---|---|---|---|
| **UI 主執行緒** | `App.run()`（程式主執行緒） | 事件迴圈；idle 時 `clock.tick(10)`，鬧鐘閃爍/翻頁動畫時提高到 30fps | 渲染前用 `App.lock`（＝`settings_lock`）短暫鎖住讀 `settings`；讀 `AppState` 一律透過 `snapshot()`（內部自己上 `AppState._lock`），不直接碰內部欄位 |
| **日曆同步執行緒**（`cal_loop`） | `sync.start_threads()` | 開機先跑一次，之後每秒檢查一次是否達 `settings.sync_interval_min`（1/3/5/10/30 分）或 `FORCE_CAL` 事件被 set | 只在階段 (a)（讀帳號目錄/註冊新帳號/存 settings）持 `settings_lock`；換 token、打 API 的階段 (b) 不持鎖；寫回 `AppState` 靠 `set_events`/`set_error` 自己的內部鎖 |
| **天氣同步執行緒**（`wx_loop`） | `sync.start_threads()` | 開機先跑一次，之後每秒檢查是否達 `WX_INTERVAL`(1800s) 或 `FORCE_WX` 事件 | 讀 `weather_lat/lon/label` 時短暫持 `settings_lock`；`fetch_weather` 網路階段不持鎖；失敗只印一行 stderr、保留舊值，不寫額外的 last_error 狀態（見下方說明） |
| **Web 執行緒**（Flask） | `webserver.start_web()`（`__main__.py` 啟動，可用 `DESKBAR_NO_WEB=1` 關閉） | Flask `app.run()` 常駐，`0.0.0.0:8080` | 鬧鐘 CRUD 直接呼叫 `AlarmStore`（自帶鎖）；`/api/calendars` 讀寫 `settings.accounts` 時持 `settings_lock`，寫回呼叫 `on_save`（即 `config.save_settings`，本身也是鎖外的原子寫入）；`POST /api/usage` 驗證完 body 直接呼叫 `AppState.set_usage`（自己的鎖），不碰 `settings_lock` |
| **在場感應執行緒**（可選） | `presence.start_presence_thread()`（僅 `presence_enabled` 且設了 `presence_mac` 才建立） | 每 45 秒一輪（`interval` 參數） | 每輪只在讀 `mac/threshold/grace/enabled` 時短暫持 `settings_lock`；`l2ping`/`hcitool` 探測（可能秒級延遲）在鎖外執行；結果寫回 `AppState.set_presence`（自己的鎖） |

Claude usage 沒有裝置端背景執行緒：資料改由 Mac 上的 agent（`tools/usage_push_snippet.py`／`tools/usage_push_demo.py`）每 60 秒主動 `POST /api/usage` 推送，deskbar 純被動接收（見上方 Web 執行緒那一列）。

工作中 sessions 走同樣的跨機資料流，但有更窄的 trust seam：`tools/work_sessions_agent.py` 在 Mac 讀 Codex／Claude 的私有本機 session 格式，先轉為 display-safe snapshot，再 `POST /api/work-sessions`。最多只保留最近的 6 筆。Pi 的 `work_sessions` 模組只保存 source、專案 basename、活動時間與 opaque `open_id`；Pygame 點擊只把該 opaque id 放進 60 秒的一次性記憶體 action queue。Mac agent 輪詢後以固定 allowlist 帶 Codex（ChatGPT）或 Claude App 到前景。Pi 永遠拿不到原 session ID、完整 cwd、prompt、response、title 或 shell command；活動時間達 30 分鐘的項目在 Mac 與 Pi 渲染層都會消失。

### 關於天氣同步的錯誤可見性

`weather_sync_once` 失敗（網路錯誤、API 格式變化等）過去是完全靜默的 `pass`，只在螢幕上以「資料變舊」被動察覺，除錯困難。目前改為失敗時印一行 `[deskbar] weather sync failed: ...` 到 stderr（systemd 環境下會進 `journalctl -u deskbar`）。

沒有額外在 `AppState` 加天氣專屬的 `last_error` 欄位：`AppState.statuses` 是「每個日曆帳號」的同步狀態，天氣不是帳號式資料，硬塞進去語意不合；若要在畫面上顯示天氣同步失敗原因，需要 `Snapshot` 新增欄位並改 `dashboard.py`/`_render_panel` 顯示邏輯——這兩處目前由另一條開發線同時在改，故本輪只做「stderr 可見」，UI 呈現留待後續整合（見本任務報告的整合說明）。
