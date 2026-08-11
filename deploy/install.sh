#!/bin/bash
set -euo pipefail

RUNTIME_ONLY=false

if [ "$#" -eq 0 ]; then
  RUNTIME_ONLY=false
elif [ "$#" -eq 1 ] && [ "$1" = "--runtime-only" ]; then
  RUNTIME_ONLY=true
else
  echo "Usage: $0 [--runtime-only]" >&2
  echo "  (no arguments) : Full system bootstrap" >&2
  echo "  --runtime-only : Routine deployment (requires existing .venv)" >&2
  exit 1
fi

DEPLOY_HOME="${DESKBAR_DEPLOY_HOME:-/home/kevin/deskbar}"
SYSTEMD_DIR="${DESKBAR_DEPLOY_SYSTEMD_DIR:-/etc/systemd/system}"
WATCHDOG_PATH="${DESKBAR_DEPLOY_WATCHDOG_PATH:-/usr/local/bin/deskbar-net-watchdog.sh}"

if [ "$RUNTIME_ONLY" = "false" ]; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3-pygame python3-venv python3-requests python3-flask fonts-noto-cjk fonts-noto-cjk-extra bluez
  # l2ping 需要 raw socket（藍牙在場感應的探測指令）；服務跑非 root，給 capability。
  L2PING=$(command -v l2ping || echo /usr/bin/l2ping)
  [ -x "$L2PING" ] && sudo setcap cap_net_raw+eip "$L2PING" || true
fi

cd "$DEPLOY_HOME"

if [ "$RUNTIME_ONLY" = "false" ]; then
  if [ ! -d .venv ]; then python3 -m venv --system-site-packages .venv; fi
else
  if [ ! -d .venv ]; then
    echo "Error: Virtual environment (.venv) not found. Please run full bootstrap first (make bootstrap)." >&2
    exit 1
  fi
fi

.venv/bin/pip install -q -r requirements.txt
sudo mkdir -p "$SYSTEMD_DIR"
sudo cp deploy/deskbar.service "$SYSTEMD_DIR/deskbar.service"
sudo systemctl daemon-reload
sudo systemctl enable deskbar

if [ "$RUNTIME_ONLY" = "false" ]; then
  # Pi Zero 2W 的 WiFi 晶片預設省電模式，閒置會打瞌睡掉線；Android 熱點看到
  # 「沒有裝置連線」又會自動關閉熱點——兩個疊加＝掉線後永遠連不回來。
  # 這裡把省電關掉並持久化（NetworkManager 層），立即生效那刀用 iw 補。
  if [ ! -f /etc/NetworkManager/conf.d/wifi-powersave-off.conf ]; then
    printf '[connection]\n# 2 = 停用 wifi 省電（Pi Zero 2W 閒置斷線坑，2026-07-27）\nwifi.powersave = 2\n' \
      | sudo tee /etc/NetworkManager/conf.d/wifi-powersave-off.conf >/dev/null
    sudo nmcli general reload 2>/dev/null || true
  fi
  sudo iw dev wlan0 set power_save off 2>/dev/null || true
  # deskbar 服務內的 nmcli 連線權限：服務跑在 systemd（非 logind 活動 session），
  # polkit 預設拒絕 NetworkManager 的修改類動作（實機錯誤：Insufficient
  # privileges；SSH 互動 session 測掃描會過，所以開發期沒炸）。放行 kevin。
  if [ ! -f /etc/polkit-1/rules.d/50-deskbar-nm.rules ]; then
    sudo tee /etc/polkit-1/rules.d/50-deskbar-nm.rules >/dev/null <<'PKEOF'
polkit.addRule(function(action, subject) {
    if (action.id.indexOf("org.freedesktop.NetworkManager.") === 0 &&
        subject.user === "kevin") {
        return polkit.Result.YES;
    }
});
PKEOF
  fi
fi

# 連線看門狗：用 NetworkManager 裝置狀態分 CONNECTED / PROGRESSING / DEAD。
# 連續 DEAD 才先請 NM 喚醒已知 profile，失敗才踢 radio（見 deploy/net-watchdog.sh 檔頭）。
sudo mkdir -p "$(dirname "$WATCHDOG_PATH")"
sudo install -m 755 deploy/net-watchdog.sh "$WATCHDOG_PATH"
sudo cp deploy/deskbar-net-watchdog.service deploy/deskbar-net-watchdog.timer "$SYSTEMD_DIR/"
sudo systemctl daemon-reload
sudo systemctl enable --now deskbar-net-watchdog.timer

if [ "$RUNTIME_ONLY" = "false" ]; then
  # 2026-08-05 教訓：RPi OS 預設 Storage=volatile，重開機日誌全失，事故查不到
  # 死因。用 drop-in 蓋掉（優先權高於 journald.conf），上限 200M 保護 SD 卡。
  sudo mkdir -p /var/log/journal /etc/systemd/journald.conf.d
  sudo tee /etc/systemd/journald.conf.d/50-deskbar-persistent.conf >/dev/null <<'EOF'
[Journal]
Storage=persistent
SystemMaxUse=200M
EOF
  sudo systemd-tmpfiles --create --prefix /var/log/journal || true
  sudo systemctl restart systemd-journald || true
fi

echo "install.sh 完成"
