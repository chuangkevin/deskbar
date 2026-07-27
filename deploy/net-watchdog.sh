#!/bin/bash
# deskbar 連線看門狗 v2：以 NetworkManager 的裝置狀態判斷，「wlan0 已連線」
# 就絕對不碰它。v1 用 ping gateway 判斷是錯的——很多 Android 熱點不回 ICMP，
# 會變成每分鐘把好好的 WiFi 關開一輪、自己製造無限斷線。
#
# 邏輯：wlan0 或任何 usb*/eth* 介面 state=connected → 一切安好，退出並清除
# 失敗計數。都沒有 → 記一次失敗；「連續第二次」失敗才踢 radio 重連（單次
# 失敗可能只是正在重連中，別打斷它）。
# 由 systemd timer 每分鐘跑一次＝掉線最慢約 2-3 分鐘自救。
set -u
STATES=$(nmcli -t -f DEVICE,STATE dev 2>/dev/null)
if echo "$STATES" | grep -qE '^(wlan0|usb[0-9]*|eth[0-9]*):connected$'; then
  rm -f /run/deskbar-watchdog.fail
  exit 0
fi
if [ ! -f /run/deskbar-watchdog.fail ]; then
  touch /run/deskbar-watchdog.fail      # 第一次失敗：先觀察一輪
  exit 0
fi
rm -f /run/deskbar-watchdog.fail
logger -t deskbar-watchdog "連續兩輪無任何連線介面，重啟 WiFi radio"
nmcli radio wifi off 2>/dev/null || true
sleep 3
nmcli radio wifi on 2>/dev/null || true
