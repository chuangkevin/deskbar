# deskbar 交接文件 (Handoff Documentation)

> [!IMPORTANT]
> **目前狀態／以此為準 (Ground Truth)**（最後更新：2026-08-11）
> - **專案基線**：Repo `/Users/kevin/Documents/Projects/deskbar` | 分支 `build/v1` | HEAD `a7a5b94` | 測試 `786 passed` | Pi 可連線且已部署。
> - **說明**：本頁最上方為最新現況。下方舊章節（如 2026-08-04 的美術重烘交接記錄、舊分支 `cinematic-scene-redesign`、舊工作目錄 `/Users/kevin/Documents/Projects/deskbar-cinematic-worktree` 以及 Pi 離線等描述）**均已過期**，僅保留作為歷史脈絡，不可視為現況。

## 0. 現狀任務分類與狀態摘要

### 已完成 (Completed)
- **指定 5 個場景重製、部署與推送**：
  - `runner` (`b077998`): 跑者像素與障礙物重製。
  - `fish` (`65ccf60`): 錦鯉水洗場景重製。
  - `fireflies` (`42ff5b6`): 暮色草原螢火蟲重製。
  - `train` (`d9d1ada`): 車窗鐵道路景重製。
  - `ink` (`01cb7ce`): 宣紙水墨場景重製。
  - **預設輪播狀態**：上述 5 款重製場景**均未進入預設輪播 `DEFAULT_SCENES`**。目前預設輪播仍維持 `stars` + `planet_horizon`，需待 Kevin 視覺審核核可後方得調整。
- **全場景審查工具修復與單元測試**：
  - 2026-08-11 修正審查工具 `dawn=05:30` (`0cbd44b`)，全數 785 項測試通過 (`785 passed`)。
  - `flow` 與 `aurora` 現況審查無發現需要重製的明確退化（此為現況評估，非「經 Kevin 核可加入預設」）。
- **螢火蟲圓形光暈回歸修正**：
  - `a7a5b94` 已修正 Pi 實機方形光斑：圓形徑向透明裁切＋逐像素亮度快取，並以裁切邊緣／角落透明度測試與 Pi 實機截圖驗證。
- **Pi 部署**：
  - 代碼已更新至 HEAD `a7a5b94` 並成功部署至 Pi 實機運行。

### 待 Kevin 確認 (Pending Kevin Confirmation)
- **重製場景進預設輪播**：
  - 重製完成之 5 款場景（`runner`, `fish`, `fireflies`, `train`, `ink`）需經 Kevin 視覺審查核可後，方可加入 `config.DEFAULT_SCENES`。
- **未實作新場景構想排程**：
  - 較早 TODO 列出之 `black hole`（黑洞吸積盤）、`alien valley`（異星山谷）、`liquid marble`（流彩大理石）等為未實作之產品構想。因缺少本次確認，標記為「需 Kevin 確認後才排入」，不可列作本次未完成 bug。
- **安全決策項目（不可擅自描述為已修復）**：
  1. **LAN 控制認證模型**：區域網路控制端點之驗證機制與權限存取策略。
  2. **Pi `kevin` 帳戶權限最小化**：縮減 `/etc/sudoers` 中 `NOPASSWD: ALL` 之權限設定。

### 需外部實測 (Requires Real-World Testing)
- **網路連線與 watchdog 重連實機觀察**：
  - 經 SSH 直接實測證實：Pi 2.4GHz AP 在 2026-08-11 13:43–13:51 出現 `ssid-not-found` / `association timeout`。
  - Watchdog v3 未重開無線電 (radio)，並於第 5 次失敗後安全重新連回。
  - **尚未結案**：尚待真實手機離席超過 2 小時之實機運作證據與完整日誌，不可以為網路根因已完全結案。

---

## 歷史紀錄（以下內容最後更新於 2026-08-04，已過期）

> ⚠️ **歷史備忘**：以下內容為 2026-08-04 舊版電影感場景重製交接說明。文中涉及之 `cinematic-scene-redesign` 分支、`deskbar-cinematic-worktree` 工作目錄、HEAD `2d94b6b`、以及「Pi 離線 / 需要 Kevin 提供 Pi 位址」等描述**已全數過期**。

# deskbar 電影感場景重製 — 交接（美術重烘）

最後更新：2026-08-04
接手者任務：**重烘 5 個場景的素材**，讓它們符合 `DESIGN.md` §7 的材質契約。
程式架構、runtime、測試、工具鏈都已完成且綠燈——**這是美術工作，不是重構工作**。

---

## 0. 機器與路徑

本文件寫於 Kevin 的 Mac（使用者 `kevin`）。**換機器只有下面第一組路徑要改**，
repo 內的相對路徑一律不變。

| 用途 | 本機絕對路徑 |
|---|---|
| 主 repo | `/Users/kevin/Documents/Projects/deskbar` |
| **工作用 worktree（在這裡做事）** | `/Users/kevin/Documents/Projects/deskbar-cinematic-worktree` |
| 素材輸出 | `<worktree>/deskbar/assets/scenes/`（81 個 PNG） |
| Baker（要改的地方） | `<worktree>/tools/scene_bakers/` |
| 場景 renderer | `<worktree>/deskbar/ui/scene_*.py` |
| 驗證證據（**gitignored，不進版控**） | `<worktree>/.omo/evidence/` |

GitHub remote：`https://github.com/chuangkevin/deskbar.git`

> 舊機器（前一棒）的路徑是 `/Users/ching/Documents/Projects/...`，若看到舊文件寫
> `ching` 一律換成本機路徑。`.omo/plans/cinematic-scene-redesign.md`（原始 15-task
> 核准計畫）只存在舊機器，本機沒有，**不需要它也能完成本任務**。

### 環境重建

```bash
cd /Users/kevin/Documents/Projects/deskbar-cinematic-worktree && uv venv --python 3.11 .venv && VIRTUAL_ENV=.venv uv pip install pygame numpy pytest requests flask qrcode google-auth google-auth-oauthlib
```

實測環境：Python 3.11.15 / pygame 2.6.1 (SDL 2.28.4) / numpy 2.4.6。
所有 headless 指令都要加 `SDL_VIDEODRIVER=dummy`。

---

## 1. Repo 狀態

- 分支：`cinematic-scene-redesign`（已 push，與 origin 同步）
- 基線：`93d73bf`（= `origin/build/v1`）
- 目前 HEAD：`2d94b6b`
- **工作區乾淨，沒有未 commit 的東西。**

```
2d94b6b feat: 預設輪播只收視覺已核可的五個場景
1765db7 test: 移除已被場景測試取代的舊行星素材測試
abe03ab fix: 還原 Sense 天氣雲與太陽球的 fBm 烘焙
f66a27c docs: 新增場景重製交接說明
c939254 feat: 建立電影感場景重製 checkpoint
93d73bf ← 基線
```

現況全綠：**509 passed**、compileall OK、generator 兩次 clean run 逐位元一致、
production 素材與 clean run 81/81 相同。

---

## 2. 你的任務：重烘這五個場景

`DESIGN.md` §7 明文禁止 focal scenery 使用
「flat circles, solid polygons, uniform gradients, untextured vector silhouettes」。
數值地板（std ≥12 / ≥160 色；train・runner 蓄意低彩 ≥48 色）**十個場景全過**，
但契約自己寫了那些地板 "never replace fresh visual review"。目視結果：

| 場景 | 現況病灶 | `DESIGN.md` §5 要求的身分 |
|---|---|---|
| **runner**（最嚴重） | 純線性漸層天空；等距重複的平滑圓形樹＋直桿；無材質實心多邊形山；平塗地面；棕色三角形障礙物。主角只有約 10px 色塊，看不出角色 | original cinematic **pixel** adventurer and obstacles in a deep **pixel** world |
| **train** | 電線桿是線條、田野平塗、太陽/月亮是純色圓。另：night 是暖橘色圓盤、day 反而淡黃，色溫關係看起來相反 | original cinematic **pixel** train with window light and multi-plane parallax |
| **fireflies** | 草地是規則鋸齒三角帶（solid polygon silhouette），地面無材質。螢火蟲光點本身可以留 | grounded dusk meadow with **grass occlusion**, haze, and depth-sorted glows |
| **fish** | 兩隻魚是無材質灰色剪影，鰭是矩形階梯狀缺口（像 bbox 沒修乾淨），沒有筆觸與 wake；背景有明顯規則垂直條紋 artifact | original **sumi-e** fish, paper/water wash, **wake**, weather-dependent depth |
| **ink** | 紙紋不錯，但 pigment bloom 實際是兩個幾何星形多邊形，不是柔性暈染；整張過空（std 17.8 全場最低） | paper grain and **soft pigment blooms** built from authored masks |

**品質標竿看這三個**（同一套工具烘出來的，證明架構做得到）：
`planet_horizon`（氣態行星帶紋、終端線柔邊、雲海浮雕、rim 光）、`aurora`、`stars`。
證據圖在 `.omo/evidence/todo12/<scene>/`。

### 專案歷史（很重要，別重蹈覆轍）

`tools/gen_scene_assets.py` 基線版的 docstring 寫著：
場景引擎 v1 用 pygame 原始幾何直畫，實機驗收「醜死了」，重蹈 weatherfx 一版的覆轍。
**貼紙感的解法是材質**——numpy 烘 per-pixel alpha 的中性白 PNG，執行期只做
「載入 → 染色 → blit ＋視差」。這次 runner/train/fireflies/fish/ink 又滑回幾何直畫。

另有三個實機驗收過的坑（`tools/scene_bakers/weather_support.py` 註解有完整記錄，
本次已修復，**不要再改那個檔**）：alpha 邊界沒歸零會在白卡上顯形成方塊、
內部密度全 1.0 會變死白一片、純白無陰影疊白卡等於隱形橡皮擦。

---

## 3. 怎麼改

### 檔案對應

| 場景 | Baker（改這裡） | Renderer（通常不用動） |
|---|---|---|
| fireflies | `tools/scene_bakers/ridges_fireflies.py` → `generate_firefly_assets` | `deskbar/ui/scene_fireflies.py` |
| fish / ink | `tools/scene_bakers/fish_ink.py` → `generate_fish_assets` / `generate_ink_assets` | `deskbar/ui/scene_fish.py` / `scene_ink.py` |
| train / runner | `tools/scene_bakers/train_runner.py` → `generate_train_assets` / `generate_runner_assets` | `deskbar/ui/scene_train.py` / `scene_runner.py` |

共用工具在 `tools/scene_bakers/common.py`：`fbm()`（決定性分形噪聲）、
`feather_alpha()`（把 alpha 在四邊壓到 0）、`save_rgba()`（2480×944 超取樣 → 1240×472
單次降取樣，並強制透明邊界）、`validate_alpha_edges()`。

### 素材清單（名稱不可改，`gen_scene_assets.py::expected_asset_names()` 會對）

```
fireflies: fireflies_base_{night,dawn,day} + grass_far, grass_near, haze, glow_0, glow_1
fish:      fish_base_{night,dawn,day} + sprite_0..2, wake_0, wake_1
train:     train_base_{night,dawn,day} + far, mid, near, window_reflection
runner:    runner_base_{night,dawn,day} + far, mid, near, sprite_sheet, obstacles
ink:       ink_base_{night,dawn,day} + bloom_0..2
```

### 硬性規格

- production canvas **1240×472**，烘焙工作畫布 **2480×944**，只降取樣一次
- `*_base_*` 是不透明底（alpha 全 255，覆蓋整個 crop）；其餘可動疊層**四邊 alpha 必須為 0**
- 場景視窗 1118×472，位於 1920×480 邏輯畫布的 `x=402..1520, y=8..480`
  （左右欄是黑底 UI，場景不會蓋到時鐘，放心構圖；但焦點物件被視窗裁切要看起來是
  刻意的取景，不是 bbox 意外切到）
- 單一 active renderer 的 decoded 素材 **≤48 MiB**
- **決定性**：固定 seed，重跑必須逐位元一致。禁止時間或未固定 seed 的亂數來源
- 材質、模糊、bloom、陰影、景深全部烘進素材；執行期只有位置與透明度會變

### 不要碰

- `tools/scene_bakers/weather_support.py`（Sense 天氣的雲與太陽球，剛修好的回歸，
  刻意保留基線的 `_fbm2d` 雙線性插值而不用 `common.fbm`——換過去等於重畫雲）
- `SCENE_KEYS` 的十個 key 與順序、`scene_tap` 契約
- `.gitignore`、`Makefile` 的 rsync 排除規則

---

## 4. 驗證（每次重烘後全跑一次）

```bash
cd /Users/kevin/Documents/Projects/deskbar-cinematic-worktree && .venv/bin/python tools/gen_scene_assets.py && SDL_VIDEODRIVER=dummy .venv/bin/python -m pytest -q
```

決定性檢查（兩次 clean run 必須逐位元一致，且與 production 相同）：

```bash
cd /Users/kevin/Documents/Projects/deskbar-cinematic-worktree && rm -rf /tmp/genA /tmp/genB && .venv/bin/python tools/gen_scene_assets.py --out /tmp/genA && .venv/bin/python tools/gen_scene_assets.py --out /tmp/genB && diff <(cd /tmp/genA && shasum -a256 *.png) <(cd /tmp/genB && shasum -a256 *.png) && diff <(cd deskbar/assets/scenes && shasum -a256 *.png) <(cd /tmp/genA && shasum -a256 *.png) && echo DETERMINISTIC-OK
```

視覺證據（晨／晝／夜 contact sheet ＋ 0/5/15 秒動態 ＋ metrics.json）：

```bash
cd /Users/kevin/Documents/Projects/deskbar-cinematic-worktree && SDL_VIDEODRIVER=dummy .venv/bin/python tools/render_scene_review.py --scene all --out .omo/evidence/todo12
```

效能（20 warm-up + 120 measured）：

```bash
cd /Users/kevin/Documents/Projects/deskbar-cinematic-worktree && SDL_VIDEODRIVER=dummy .venv/bin/python tools/benchmark_scenes.py --scene all --warmups 20 --frames 120 --out .omo/evidence/todo13/benchmark.json
```

門檻：p95 ≤80 ms、單 renderer decoded <48 MiB、RSS <200 MiB。
本機 Mac 目前最差 p95 19.46 ms / decoded 20.09 MiB / RSS 91.0 MiB，餘裕很大。

---

## 5. 規則（前一棒的約束，仍然有效）

- **不要 commit** `.omo/`、`local.mk`、設定檔、憑證、快取、QA 證據
- **正常 push，禁止 force-push**
- 中文（繁體）commit message，維持 repo 現有風格：`type: 摘要（括號補實證）`
- 場景通過視覺核可前**不要**加回 `DEFAULT_SCENES`（`deskbar/config.py:13`，
  有測試 `test_default_rotation_only_contains_visually_approved_scenes` 釘著）。
  重烘完並經 Kevin 目視核可後，才把該場景加進去並同步改那條測試。

---

## 6. 尚未完成 / 已知不可用

- **五個場景的重烘**（本文件的主任務）
- **合併回 `build/v1`**：本機閘門已全過，但等美術完成後再一起處理
- **Pi 實機部署與閘門（p95 ≤80 ms、RSS <200 MiB）完全未驗**：
  本機沒有 `local.mk`，`deskbar.local` 無法解析，`~/.ssh/config` 無對應 Host，
  `known_hosts` 無紀錄。`~/.ssh/kevinhome_key` 存在但目標主機未知。
  Pi 端路徑是 `/home/kevin/deskbar`，部署走 `make deploy`（需先建 `local.mk`，
  範例見 `local.mk.example`）。**需要 Kevin 提供 Pi 位址並確認開機。**
- **basedpyright 未安裝**（先前拒絕安裝），**不可聲稱 LSP clean**；ruff 也沒裝
- 專案無 LOC guard 測試

---

## 7. 前一棒到本棒之間修掉的東西（避免重犯）

拆 baker 時 `weather_support.py` 把 `cumulus_0/1`、`sun_ball` 從 numpy fBm 烘焙改寫成
`pygame.draw.circle` 疊圓，一次踩回三個實機驗收過的病灶（雲邊界 alpha 27/34 未歸零、
內部密度起伏消失、太陽高光壓平）。前一棒把 production 重新生成讓 81 個 hash「完全一致」，
實際上是用退化版覆蓋掉好素材才一致的——**hash 一致不等於素材正確**。
已於 `abe03ab` 逐位元還原。同批也刪掉了永遠紅燈的 `tests/test_planet_horizon_assets.py`
（斷言已拆分刪除的舊 planet master，契約已被 `tests/test_scene_planet_flow.py` 接手）。
