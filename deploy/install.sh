#!/bin/bash
set -euo pipefail
sudo apt-get update -qq
sudo apt-get install -y -qq python3-pygame python3-venv python3-requests python3-flask fonts-noto-cjk
cd /home/kevin/deskbar
if [ ! -d .venv ]; then python3 -m venv --system-site-packages .venv; fi
.venv/bin/pip install -q -r requirements.txt
sudo cp deploy/deskbar.service /etc/systemd/system/deskbar.service
sudo systemctl daemon-reload
sudo systemctl enable deskbar
# Pi Zero 2W 的 WiFi 晶片預設省電模式，閒置會打瞌睡掉線；Android 熱點看到
# 「沒有裝置連線」又會自動關閉熱點——兩個疊加＝掉線後永遠連不回來。
# 這裡把省電關掉並持久化（NetworkManager 層），立即生效那刀用 iw 補。
if [ ! -f /etc/NetworkManager/conf.d/wifi-powersave-off.conf ]; then
  printf '[connection]\n# 2 = 停用 wifi 省電（Pi Zero 2W 閒置斷線坑，2026-07-27）\nwifi.powersave = 2\n' \
    | sudo tee /etc/NetworkManager/conf.d/wifi-powersave-off.conf >/dev/null
  sudo nmcli general reload 2>/dev/null || true
fi
sudo iw dev wlan0 set power_save off 2>/dev/null || true
# 連線看門狗：掉線後 WiFi 常卡殭屍態不重連，每分鐘 gateway 探活、不通就
# 踢 radio 重連（見 deploy/net-watchdog.sh 檔頭）。
sudo install -m 755 deploy/net-watchdog.sh /usr/local/bin/deskbar-net-watchdog.sh
sudo cp deploy/deskbar-net-watchdog.service deploy/deskbar-net-watchdog.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now deskbar-net-watchdog.timer
echo "install.sh 完成"
