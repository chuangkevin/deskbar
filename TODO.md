# deskbar TODO（2026-08-03 交接）

新 session 接手時從這裡開工。品質流程鐵則：**烘焙素材管線**（tools/gen_scene_assets.py，
numpy fBm，素材四邊 alpha 必須歸零——見 test_cumulus_assets_have_fully_transparent_borders
的血淚）＋每款完成先渲染「晨/晝/夜」驗證圖給使用者過目，過了才進預設輪播。

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
