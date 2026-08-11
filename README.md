# deskbar

A tactical calendar dashboard for an 8.8" 1920×480 ultrawide touchscreen, driven by a Raspberry Pi Zero 2 W. Multi-account Google Calendar swimlanes, a flip-clock panel, weather, alarms with a phone-friendly web UI, and a Claude Code usage gauge — all rendered by a single lightweight Pygame process with no desktop environment (target <200MB RAM on 512MB hardware).

樹莓派 Zero 2 W ＋ 8.8 吋 1920×480 長條觸控屏的桌面資訊儀表板。多 Google 帳號行事曆泳道、翻頁時鐘、天氣、鬧鐘（含手機網頁遙控）、Claude Code 用量油表，全部由單一 Pygame 程序直繪 framebuffer，不跑桌面環境，24 小時常駐。

**狀態**：核心功能已實作並有測試覆蓋，持續迭代中。設計文件見 [`docs/superpowers/specs/2026-07-26-deskbar-design.md`](docs/superpowers/specs/2026-07-26-deskbar-design.md)；模組架構見 [`docs/architecture.md`](docs/architecture.md)。

---

## 定位

放在桌上、24 小時亮著的「資訊長條」，不是另一個要解鎖才看得到的螢幕。掃過去就知道：現在幾點、今天/這週誰有什麼行程、天氣如何、鬧鐘設了沒。所有互動都設計成「路過戳一下」等級的觸控——沒有輸入法、沒有鍵盤、沒有需要盯著看的複雜設定流程。

## 硬體

| 項目 | 規格 / 備註 |
|---|---|
| 主機 | Raspberry Pi Zero 2 W（512MB RAM） |
| 螢幕 | 8.8 吋長條觸控屏，原生解析度 480×1920（直向），HDMI 輸出＋USB 觸控 |
| Wi-Fi | **僅支援 2.4GHz**——Pi Zero 2 W 的內建無線晶片不吃 5GHz，家中路由器若開了 5GHz-only 或雙頻合併 SSID 要另外切一個 2.4G 專用網路 |
| 排線 | 面板走 CSI／窄版排線，走線空間比一般 HDMI 排線緊，機殼設計/走線時要預留 |
| 供電 | 建議 5V/2.5A 以上電源，長時間 24h 常駐 + 觸控 + Wi-Fi 同時工作，弱電源容易觸發欠壓降頻 |

> 螢幕原生方向是直向 480×1920；deskbar 應用內以橫向 1920×480 邏輯座標作畫，輸出前旋轉 90°/270°（設定頁可切換），觸控座標做同一旋轉的反向換算。

## 功能

- **多帳號 Google Calendar**：每個帳號一條獨立泳道（左緣色條＋可自訂標籤：工作／個人／家庭…），唯讀同步（`calendar.readonly`），單一帳號授權失效不影響其他帳號。
- **四種顯示寬度**：半天／日／週／月，右上角循環切換；兩種顯示模式——「河道」（按帳號分道）與「行程」（按天分塊直欄清單）。
- **全視圖滑動平移**：時間軸區域左右拖曳即可平移錨點，離開「現在」時顯示「回到今天」；平移範圍以本地同步窗口（今天 −7 天 ～ +30 天）為界。
- **鬧鐘系統**：裝置端新增/啟停/刪除，支援單次或依星期重複；到點全螢幕閃爍覆疊，點任意處關閉。**同時提供手機網頁遙控**（Pi 起一個內網 Flask 頁面，同網段手機開瀏覽器就能管理鬧鐘，免登入 App）。
- **QR Code**：設定頁顯示 QR，手機掃了直接開啟上述鬧鐘網頁，不用手動輸入網址。
- **翻頁時鐘動畫**：左側大時鐘分鐘變化時播放翻牌卡片動畫。
- **天氣**：Open-Meteo 現況溫度＋當日高低溫，免 API key。
- **螢幕旋轉**：設定頁一鍵在 90°/270° 間切換，免重開機。
- **Claude Code 用量油表**：右欄顯示個人 Claude Code 用量（5 小時視窗／本週／Fable 方案）三組進度條，純資訊顯示不可互動。裝置端不做任何 OAuth 或網路抓取——資料由 Mac 上常駐的 agent 讀本機 Keychain 憑證、打官方 usage API，再主動 POST 推給 deskbar（見下方疑難排解）。
- **離線快取**：行事曆與天氣資料落地快取；斷網時用快取渲染並標示資料年齡。
- **強制同步**：點擊同步狀態列立即觸發一輪日曆＋天氣同步；同步頻率（1/3/5/10/30 分鐘）可在設定頁調整。

## 架構

```
deskbar/
├── deskbar/                  # 應用主體（Pi 上跑，Mac dev 模式共用同一套）
│   ├── __main__.py           # 進入點：組裝 store/settings/同步執行緒/web/App
│   ├── config.py             # Settings 載入/儲存（原子寫入）
│   ├── store.py              # 執行緒安全的 AppState（事件/天氣/用量/在場狀態快照）
│   ├── alarms.py             # 鬧鐘 CRUD 與到點判斷（原子寫入）
│   ├── sync.py               # 日曆／天氣背景同步執行緒
│   ├── auth.py                # Google OAuth token 刷新（refresh_token → access_token）
│   ├── gcal.py                # Google Calendar API 唯讀用戶端
│   ├── weather.py             # Open-Meteo 用戶端
│   ├── models.py              # Event 正規化（HTML 清洗、時區、整日/跨日）
│   ├── layout.py              # 泳道/子車道佈局純函數
│   ├── viewwin.py             # 顯示窗口純函數（半天/日/週/月 → 起訖時間）
│   ├── transform.py           # 旋轉矩陣與觸控座標反解
│   ├── presence.py            # 藍牙在場感應（可選功能）
│   ├── claudeusage.py         # Claude Code usage 唯讀資料層
│   ├── webserver.py           # Flask：鬧鐘/日曆管理 API＋手機網頁
│   └── ui/                    # Pygame 渲染與觸控分派
│       ├── app.py             # 主迴圈、事件分派、旋轉輸出、切換過場
│       ├── theme.py           # 顏色/字型/量測（含 BGR 面板色序開關）
│       ├── dashboard.py       # 主畫面組裝（左面板＋時間軸/河道/行程）
│       ├── settings_view.py / alarm_view.py / alarm_overlay.py / detail.py
│       └── weekgrid.py / monthgrid.py / agenda.py / usagewidget.py / …
├── tools/                     # Mac 端工具（帳號授權精靈、渲染驗證矩陣、登入腳本）
├── deploy/                    # systemd service、Pi 端安裝腳本
├── docs/                      # 架構與設定說明文件
└── tests/                     # pytest（Mac 上跑，含 headless pygame 渲染測試）
```

完整模組職責一覽與資料流／執行緒圖見 [`docs/architecture.md`](docs/architecture.md)。

## 安裝

1. **燒錄系統**：用 Raspberry Pi Imager 燒 Raspberry Pi OS（64-bit），燒錄時直接設好主機名、帳號、**2.4GHz** Wi-Fi、SSH 公鑰。設定開機進文字模式（不進桌面）省 RAM。
2. **強制螢幕解析度**（面板 EDID 常被誤判時需要）：編輯 Pi 開機分割區的 `cmdline.txt`，加上：
   ```
   video=HDMI-A-1:480x1920@60 fbcon=rotate:1 consoleblank=0
   ```
3. **部署程式碼**：
   ```bash
   cp local.mk.example local.mk   # 改成你的實際 PI/KEY/DEST（不進版控）
   make bootstrap                 # 首次 Pi / OS provisioning 用（完整系統 bootstrap ＋ 重啟 Deskbar）
   make deploy                    # 後續日常更新用（快速 runtime deploy ＋ 重啟 Deskbar）
   ```
   * **首次 Pi／OS provisioning**：執行 `make bootstrap`（會進行 `apt-get` 系統套件安裝、 capability 設定、`.venv` 建立、pip 相依安裝、Wi-Fi 省電/polkit/journald 設定與看門狗服務啟用，最後重啟 Deskbar）。
   * **後續日常更新**：執行 `make deploy`（僅進行程式碼同步、更新 Python 相依與 service/watchdog 檔、daemon-reload，不跑 `apt-get` 或系統設定，最後重啟 Deskbar）。
   * 兩者都會自動重啟 Deskbar。
4. **GCP 設定**（一次性，約 15 分鐘）：建立專案、啟用 Calendar API、OAuth 同意畫面發布為正式版、建立「電腦版應用程式」OAuth 用戶端，下載 `client_secret.json` 放到 Mac 的 `~/.config/deskbar/`。完整步驟見 [`docs/gcp-setup.md`](docs/gcp-setup.md)。
5. **加入帳號**（每個要顯示的 Google 帳號跑一次）：
   ```bash
   make add-account
   ```
   在 Mac 瀏覽器完成 Google 登入後，工具會自動把授權部署到 Pi。

## 設定檔位置

所有執行期資料都在 Pi（或本機 dev 環境）的使用者目錄下，**不進 repo**：

| 路徑 | 內容 |
|---|---|
| `~/.config/deskbar/settings.json` | 顯示設定：帳號日曆開關、泳道標籤、天氣座標、旋轉方向、同步頻率… |
| `~/.config/deskbar/client_secret.json` | GCP 桌面型 OAuth client（chmod 600） |
| `~/.config/deskbar/accounts/<email>.json` | 各 Google 帳號 refresh token（chmod 600） |
| `~/.config/deskbar/alarms.json` | 鬧鐘清單 |
| `~/.cache/deskbar/events.json`、`weather.json` | 離線快取（含抓取時間戳） |

對應的 `.gitignore` 規則：`client_secret.json`、`accounts/`、`settings.json`、`*.token.json`、`.cache/` 一律排除，只有 `local.mk.example` 這類 `*.example` 範例檔進版控。本機開發時可用環境變數 `DESKBAR_CONFIG_DIR` / `DESKBAR_CACHE_DIR` 指到別的目錄（測試套件就是這樣隔離的）。

## 開發指令

```bash
make dev     # Mac 上開 1920×480 視窗跑同一套 UI（DESKBAR_DEV=1 DESKBAR_FAKE=1，假資料、不用連 Pi）
make test    # .venv/bin/python -m pytest -q
```

**渲染驗證矩陣**：改版面時人眼核對用，把顯示寬度×模式×錨點全排列＋設定頁/鬧鐘頁/浮層等特殊畫面各存一張 PNG：

```bash
.venv/bin/python tools/render_matrix.py --events /tmp/pi-events.json --out /tmp/matrix
```

開發環境為 Python 3.9（含 `from __future__ import annotations` 以使用 PEP 604 `X | Y` 型別寫法）。

## 疑難排解

| 現象 | 原因 / 處理 |
|---|---|
| 開機螢幕空白，或解析度明顯不對 | 面板 EDID 沒被正確識別。在 `cmdline.txt` 加 `video=HDMI-A-1:480x1920@60` 強制模式（見上方安裝步驟 2） |
| 畫面顏色整個反了（紅藍互換） | 面板排線只吃 BGR 色序。啟動時加環境變數 `DESKBAR_BGR=1`（寫進 `deskbar.service` 的 `Environment=`） |
| 中文字變成方框（tofu） | 缺 CJK 字型。確認 Pi 上已裝 `fonts-noto-cjk`（`deploy/install.sh` 會自動安裝），或用 `DESKBAR_FONT` 指向自備字型檔 |
| Google 授權每 7 天就失效，泳道顯示「需重新授權」 | OAuth 同意畫面還停在「測試」模式。到 GCP Console 把發布狀態改成「正式版」（見 `docs/gcp-setup.md` 第 3 步），發布後長期有效 |
| 登入時出現「Google 尚未驗證這個應用程式」 | 個人自用未驗證應用程式的正常提示，點「進階」→「前往 deskbar（不安全）」即可；授權範圍只有唯讀查看日曆 |
| 觸控方向跟畫面對不起來 / 點哪都不準 | 先確認設定頁「旋轉螢幕」是否切到正確的 90°/270°；`deskbar/transform.py` 的觸控反解矩陣跟目前旋轉角度綁定，兩者要一致 |
| Claude usage 油表一直顯示「usage 未推送」 | deskbar 本身不抓取 usage，要靠 Mac 上的 agent 主動 POST `/api/usage`（見 `tools/usage_push_snippet.py`／`tools/usage_push_demo.py`）；確認該 agent 有在跑、網路能連到 Pi，若 Pi 上設了 `DESKBAR_PUSH_TOKEN` 環境變數，推送端也要帶同樣的 `X-Deskbar-Token` header 否則會被 401 拒絕 |

## 工作中 sessions（Codex／Claude）

Deskbar 的「工作中 sessions」只顯示最近活動**少於 30 分鐘**的 session，最多保留最新 **6 筆**。1920×480 主畫面會顯示前三筆與總數，點入可看完整六筆。Mac collector 只會送來源、專案資料夾名稱、最後活動時間與一次性開啟碼；不會送 prompt、回覆、對話標題、完整路徑、session ID 或任何憑證。

先在 Mac 驗證一次推送：

```bash
DESKBAR_URL=http://100.98.35.59:8080 \
  .venv/bin/python tools/work_sessions_agent.py --once
```

長駐時可將 [`deploy/com.deskbar.work-sessions.plist`](deploy/com.deskbar.work-sessions.plist) 複製到 `~/Library/LaunchAgents/`，再以 `launchctl bootstrap gui/$(id -u) ...` 載入；若 Pi 設定了 `DESKBAR_PUSH_TOKEN`，請在啟動 agent 的環境提供同名變數，勿寫進 plist 或版控。停止／回滾：`launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.deskbar.work-sessions.plist` 後刪除該副本即可。

點 session 目前只會把對應的 **Codex（ChatGPT）或 Claude App 帶到前景**。兩者目前都沒有經驗證的特定對話深連結，因此不會假稱可精準跳進某一個 private session。

## 雙端網路診斷觀測（Net Observer & Probe）

為了排查長時閒置後 Pi 與 Mac 間 Tailnet / Wi-Fi 的連線狀況，系統提供雙端純觀測診斷工具（僅記錄狀態變化，永不觸發重連、radio 或修復動作）：

> 日常 `make deploy` 不會安裝、啟用或重設任何網路元件；這些診斷／復原元件只會在明確執行 `make bootstrap` 時處理。

- **Pi 側 Observer (`deploy/net-observer.sh`)**：由 `deskbar-net-observer.timer` 每 60 秒啟動一次，純唯讀檢查 `wlan0_connected`、`route_via_wlan0`、`dns_resolution`、`public_ip_http` 與 `deskbar_local_http` 5 項狀態。DNS 與公開 HTTP 檢查刻意不走私有 Tailnet／反向代理路徑；僅在狀態發生變化時透過 systemd logger 寫入一列結構化日誌。
  - **查看 Pi 日誌**：`journalctl -u deskbar-net-observer.service -t deskbar-net-observer -n 50`
- **Mac 側 Probe (`tools/deskbar_net_probe.py`)**：Mac 端常駐 probe，預設每 15 秒檢查 Pi Tailnet HTTP 與 `desk.sisihome.org` HTTPS。僅在狀態變化時記錄至 `/tmp/deskbar-net-probe.log`。
  - **單次執行測試**：`.venv/bin/python tools/deskbar_net_probe.py --once`
  - **查看 Mac 日誌**：`tail -f /tmp/deskbar-net-probe.log`


## 授權與資料範圍

僅使用 Google Calendar `calendar.readonly` 唯讀 scope；token 與 client secret 檔案權限一律 600；SSH 僅金鑰登入。Repo 本身可公開：任何帳號憑證、快取、實際地點座標都在 `.gitignore` 排除範圍，只留 `*.example` 範例檔。
