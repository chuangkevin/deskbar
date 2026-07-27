#!/bin/bash
# deskbar 連線看門狗：default gateway ping 不通就把 WiFi radio 關開一輪，
# 逼 NetworkManager 對所有 autoconnect 網路完整重連。
#
# 為什麼需要：實測 Pi Zero 2W 掉線後（省電模式打瞌睡、或熱點短暫消失）
# 常卡在「熱點明明在、就是不重連」的殭屍狀態，只能人手重開機。由
# systemd timer 每分鐘跑一次本腳本＝裝置自救，符合「只要開機就要自動
# 恢復」的專案鐵則。
#
# 注意：走 USB 網路共享（usb0）時 default route 在 usb0，ping 得通就
# 直接 exit 0，完全不會碰 WiFi。
set -u
GW=$(ip -4 route show default | awk '{print $3; exit}')
if [ -n "${GW:-}" ] && ping -c 1 -W 3 "$GW" >/dev/null 2>&1; then
  exit 0
fi
logger -t deskbar-watchdog "gateway 不通（GW=${GW:-無}），重啟 WiFi radio"
nmcli radio wifi off 2>/dev/null || true
sleep 3
nmcli radio wifi on 2>/dev/null || true
