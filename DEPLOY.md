# 部署手冊

真實的主機 IP／網域**不寫進本文件**（公開 repo 淨空原則，commit 前的敏感字串
掃描會擋）。以下用佔位符，真實值在部署機的 `~/.ssh/config`（建議設 Host 別名）
或私人筆記。

## 架構

```
開發機 (Mac) ──rsync over ssh──▶ Pi Zero 2W（實機，systemd 服務 deskbar）
                                     │  :8080 Flask（網頁遙控＋API）
反向代理主機（家用伺服器, Docker caddy）
    <DESK_DOMAIN> ──reverse_proxy──▶ <PI_TAILSCALE_IP>:8080
```

- 所有機器都在同一個 tailnet；網域是 wildcard A 記錄指到代理主機的
  tailscale IP——**tailnet 外連不進來**（沒開 Tailscale 的裝置打不開網頁
  是設計，不是故障）。
- Pi 上程式路徑 `/home/kevin/deskbar/`，服務名 `deskbar`。

## 日常部署（Mac → Pi）

```bash
# <PI> 建議在 ~/.ssh/config 設別名（HostName=Pi 的 tailscale IP、User、IdentityFile）
rsync -a --delete \
  --exclude .git --exclude .venv --exclude .devhome \
  --exclude __pycache__ --exclude .superpowers \
  ~/Documents/Projects/deskbar/ <PI>:/home/kevin/deskbar/

ssh <PI> "sudo systemctl restart deskbar"
```

### 部署後驗證（三板斧）

```bash
ssh <PI> "systemctl is-active deskbar && journalctl -u deskbar --since '-30s' --no-pager | grep -c Traceback"
# 期望：active + 0

curl -s http://<PI_TAILSCALE_IP>:8080/api/notes | head -c 100   # API 活著
curl -s http://<PI_TAILSCALE_IP>:8080/api/screenshot -o /tmp/pi.png  # 實機畫面抓回來看
```

## 部署前必做

1. **敏感字串掃描**：`git diff --cached` 過一遍家用網域/內網 IP/公司字串
   （歷史上 commit 訊息與註解都要掃）。
2. **測試綠**：`SDL_VIDEODRIVER=dummy .venv/bin/python -m pytest tests/ -q`。
3. 素材有重烤的話確認 `deskbar/assets/**` 有跟著 commit（rsync 是整目錄同步，
   但 repo 才是真相來源）。

## 網頁遙控的反向代理（一次性設定，已完成）

代理主機上 Caddy 跑在 Docker（container 名 `caddy`），路由表掛載自
`~/DockerCompose/caddy/routes.caddyfile`，在 `*.<家用網域>` site block 內
`import`。新增子網域的步驟：

```
# routes.caddyfile 內、catch-all handle 之前，照既有格式加：
@desk host desk.<家用網域>
handle @desk {
    reverse_proxy <PI_TAILSCALE_IP>:8080 {
        import proxy_common
    }
}
```

```bash
docker exec caddy caddy reload --config /etc/caddy/Caddyfile
curl -s -o /dev/null -w "%{http_code}" https://desk.<家用網域>/   # 期望 200
```

踩坑備忘：wildcard DNS＋TLS 一直都會通（憑證是 `*.<家用網域>` 一張），
「TLS 握手成功但 404 No Caddy route」＝路由沒加，不是 DNS/憑證問題。

## 本機 dev 視窗（不碰實機）

```bash
cd ~/Documents/Projects/deskbar
DESKBAR_DEV=1 .venv/bin/python -m deskbar          # 開發視窗
# 隔離設定：加 DESKBAR_CONFIG_DIR=/tmp/deskbar-demo（不污染正式 settings）
```

## 相關文件

- `TODO.md`——待辦與交接（場景排程、開機提速待辦）
- `HANDOFF.md`——Mac usage agent 的安裝交接（右欄油表資料來源）
