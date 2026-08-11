# deskbar TODO

> [!IMPORTANT]
> **目前狀態／以此為準 (Ground Truth)**（最後更新：2026-08-11）
> - **專案基線**：Repo `/Users/kevin/Documents/Projects/deskbar` | 分支 `build/v1` | HEAD `0cbd44b` | 測試 `785 passed` | Pi 可連線且已部署。
> - **說明**：本頁上方為現況最新資訊。下方舊章節（如 2026-08-03 交接記錄）均已過期，僅保留作為歷史參考，不可視為現況。

## 1. 現狀任務分類

### 已完成 (Completed)
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
  - **尚未結案**：尚待真實手機離席超過 2 小時之實機維運紀錄與 Log 證據，不可以為網路根因已完全結案。

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
