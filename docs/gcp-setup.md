# GCP 一次性設定（約 15 分鐘，只做一次）

做完之後，每新增一個 Google 帳號只要在 Mac 上跑一行指令。

## 1. 建立專案

1. 開 https://console.cloud.google.com
2. 左上專案選單 → 新增專案 → 名稱 `deskbar` → 建立

## 2. 啟用 Calendar API

「API 和服務」→「程式庫」→ 搜尋 **Google Calendar API** → 啟用

## 3. OAuth 同意畫面

「API 和服務」→「OAuth 同意畫面」

- User Type：**外部** → 建立
- 應用程式名稱 `deskbar`；使用者支援電子郵件、開發人員聯絡資訊填自己的信箱
- 範圍：新增 `https://www.googleapis.com/auth/calendar.readonly`
- 測試使用者：可略過
- **發布狀態 →「發布應用程式」（正式版）**

> 這一步最關鍵：停留在「測試」模式的話，授權每 7 天就會失效、螢幕會變成「需重新授權」。發布後不會過期。
> 發布時 Google 問「是否需要驗證」——個人自用選擇不驗證即可，只會在登入時多一個警告畫面。

## 4. 建立 OAuth 用戶端

「API 和服務」→「憑證」→ 建立憑證 → **OAuth 用戶端 ID**

- 應用程式類型：**電腦版應用程式**
- 名稱：`deskbar-mac`
- 建立後下載 JSON

## 5. 放到 Mac

把下載的 JSON 存成：

```
~/.config/deskbar/client_secret.json
```

## 6. 加入帳號（每個帳號跑一次）

```bash
cd ~/Documents/Projects/deskbar && make add-account
```

- 瀏覽器會跳出 Google 登入（個人帳號、公司 Workspace 帳號都可以）
- 出現「Google 尚未驗證這個應用程式」→ 進階 →「前往 deskbar（不安全）」→ 繼續
  （這是未驗證應用程式的正常提示；授權範圍只有「查看日曆」唯讀）
- 完成後工具會自動把授權部署到 Pi，並印出該帳號的日曆數量
- 螢幕最慢 5 分鐘後出現該帳號的泳道；想立刻看到就重啟服務：
  ```bash
  ssh -i ~/.ssh/id_ed25519 pi@deskbar.local "sudo systemctl restart deskbar"
  ```

## 7. 切換到真實資料模式

第一次接入真帳號後，關掉示範資料：

```bash
ssh -i ~/.ssh/id_ed25519 pi@deskbar.local "sudo rm -f /etc/systemd/system/deskbar.service.d/fake.conf && sudo systemctl daemon-reload && sudo systemctl restart deskbar"
```

## 常見問題

| 現象 | 原因與處理 |
|---|---|
| 泳道顯示「需重新授權」 | 該帳號授權失效（多半是同意畫面仍停留在測試模式）→ 確認已發布，再跑一次 `make add-account` |
| 授權完沒有 refresh token | 該帳號先前授權過 → 到 https://myaccount.google.com/permissions 移除 deskbar 後重跑 |
| 行程沒出現 | 設定頁確認該帳號的日曆有勾選；或等下一次同步（每 5 分鐘） |
