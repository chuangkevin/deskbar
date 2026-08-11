# deskbar TODO

> [!IMPORTANT]
> **目前狀態／以此為準 (Ground Truth)**（最後更新：2026-08-11）
> - **已部署程式碼基線**：Repo `/Users/kevin/Documents/Projects/deskbar` | 分支 `build/v1` | 測試 `792 passed` | Pi 可連線且已部署；提交版本請以 `git log -1` 為準。
> - **說明**：本頁上方為現況最新資訊。下方舊章節（如 2026-08-03 交接記錄）均已過期，僅保留作為歷史參考，不可視為現況。

## 1. 現狀任務分類

### 已完成 (Completed)
- **工作中 sessions 功能（已部署／驗證）**：Mac LaunchAgent 每 15 秒彙整 Codex／Claude 最近 30 分鐘活動，最多保留 6 筆；Pi 只接收 display-safe 資料與一次性 opaque 開啟碼。場景／行事曆／待辦／便條中欄模式都會在右欄優先顯示 sessions；摘要顯示前三筆與總數、點入可檢視完整六筆。點擊目前僅帶來源 App 到前景，非精準對話深連結；815 tests passed，Pi 實機與 LaunchAgent 已驗證。
- **交接指定 5 個場景重製與部署推送**：
  - `runner` (`b077998`): 跑者像素與障礙物重製。
  - `fish` (`65ccf60`): 錦鯉水洗場景重製。
  - `fireflies` (`42ff5b6`): 暮色草原螢火蟲重製。
  - `train` (`d9d1ada`): 車窗鐵道路景重製。
  - `ink` (`01cb7ce`): 宣紙水墨場景重製。
  - 上述 5 款場景已完成開發、測試、部署至 Pi 並完成推送。**未加入預設輪播 `DEFAULT_SCENES`**（目前預設仍為 `stars` + `planet_horizon`，需待 Kevin 視覺審查核可後方可變更）。
- **審查工具與現況評估**：
  - 2026-08-11 修正全場景審查工具 `dawn=05:30` (`0cbd44b`)，全數 785 項測試通過。
  - `flow` 與 `aurora` 現況審查無發現需要重製的明確退化（此為現況評估，非「經 Kevin 核可加入預設」）。
- **螢火蟲圓形光暈回歸修正**：
  - `a7a5b94` 修正實機出現的方形光斑：以圓形徑向透明裁切取代方形遮罩，並改為逐像素亮度快取；已加上裁切邊緣／角落透明度回歸測試、Pi 實機截圖驗證、部署與推送。
- **網路 watchdog 硬重置熔斷**：
  - `37de8bc` 限制 Wi-Fi radio 在 6 小時內最多硬重啟 2 次；熔斷期間仍會依原規則嘗試已知 NetworkManager profile，防止長時間 AP 不可見時反覆切換組合式 Wi-Fi／藍牙晶片。已完成 shell 模擬回歸測試、Pi 安裝 hash 與服務驗證。
- **部署流程拆分**：
  - `cf36358` 將首次 Pi／OS bootstrap 與日常 runtime deploy 分開：`make bootstrap` 保留 apt／系統設定，`make deploy` 不再碰 apt 或 Wi-Fi 設定，只更新 Python 相依、unit、watchdog 後重啟 Deskbar。已以 shell integration test 與 Pi 新 PID／截圖實測驗證。

### 待 Kevin 確認 (Pending Kevin Confirmation)
- **新場景產品構想排程**：
  - 較早 TODO 中提到的 `black hole`（黑洞吸積盤）、`alien valley`（異星山谷）、`liquid marble`（流彩大理石）等為未實作之產品構想。因本次未獲指示確認，標記為「需 Kevin 確認後才排入」，不可列作本次未完成 bug。
- **預設輪播調整**：
  - 重製完成之 5 款場景（`runner`, `fish`, `fireflies`, `train`, `ink`）需經 Kevin 視覺審核認可後，再決定是否調整 `config.DEFAULT_SCENES`。
- **安全決策項目（未修復）**：
  1. **LAN 控制認證模型**：區域網路控制端點之驗證機制與存取控制策略。
  2. **Pi `kevin` 帳戶權限最小化**：縮減 `/etc/sudoers` 中 `NOPASSWD: ALL` 之權限範圍。

### 需外部實測 (Requires Real-World Testing)
- **網路斷線與自動重連實機驗證**：
  - 經 SSH 直接實測證實：Pi 2.4GHz AP 於 2026-08-11 13:43–13:51 出現 `ssid-not-found` / `association timeout`。
  - Watchdog v3 未重開無線電 (radio)，並於第 5 次失敗後安全重新連回。
  - **2026-08-11 14:34 實證**：NetworkManager 對所有已存 Wi-Fi profile 記錄 `ssid-not-found`／association timeout；watchdog 14:40 才做本次 boot 的第一次 radio restart。Bluetooth service 與 kernel 沒有 HCI timeout／控制器死鎖證據。使用者 48 秒後即重開機，故無法判斷 radio restart 後是否能自行回復。
  - **尚未結案**：watchdog 已加硬重置熔斷，但仍待真實手機離席超過 2 小時之實機維運紀錄與 Log 證據，不可以為網路根因已完全結案。

---

## 2. 歷史紀錄（已過期 - 2026-08-03 交接資訊）

> ⚠️ **歷史備忘**：以下內容為 2026-08-03 舊交接資訊，文中提及之 Pi 離線、舊場景未過驗收等描述均已過期，現況請以上方第 1 節為準。

## 場景（依使用者指定順序，參考圖在 2026-08-03 對話）

1. **行星地平線**（首發）——軌道視角、巨行星壓在雲海地平線、藍白邊緣光。
   1920×480 長條屏天生構圖。
2. **黑洞吸積盤**——Interstellar 風格，烘焙發光盤面、執行期極慢旋轉。
3. **異星山谷**——尖峰山脈（重用 ridge 烘焙技術）＋星空掛雙巨行星。
4. **流彩大理石**——飽和粉藍黃液態漩渦，烘焙紋理＋緩慢平移/色彩呼吸。

## 其他

5. **六款舊場景翻新或淘汰**——flow/fish/aurora/train/runner/ink 未過驗收，
   逐一烘焙重做或與使用者確認淘汰（scenes_enabled 預設目前只有 stars/fireflies/ridges…
   確認 config.DEFAULT_SCENES 現狀）。
6. **Pi 上線後總部署**——rpi2w（tailnet）目前離線。上線後：rsync build/v1 全部
   累積變更（久坐提示/日光儀/場景引擎/Sense 左欄/usage 配速）→ 重啟 deskbar
   → `systemd-analyze blame` 開機提速（服務不等網路、砍閒置服務、config.txt 修剪）。
   usage agent 交接：mba-kevin 照 HANDOFF.md 第 5 節安裝後，右欄油表才會恢復推送。

## 本機 dev 備忘

- demo 視窗：`DESKBAR_DEV=1 .venv/bin/python -m deskbar`（設定隔離用 DESKBAR_CONFIG_DIR）
- Mac 視窗（cocoa）specific：素材必須 convert_alpha、避免 set_alpha 疊 per-pixel
  alpha（2026-08-03「奇怪的方塊」四連環的教訓，詳見 scenes._scene_sprite docstring）
- 驗收者品味：乾淨專業、素材級質感（貼紙感=打回票）、參考圖導向
