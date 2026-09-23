#!/usr/bin/env bash
# 把 repo 的 tools/ 同步到 Mac 推送 agent（~/.deskbar-agent/），重啟後等到第一次推送成功。
# 以前靠手動 cp，忘了就會「repo 修好了、實際在跑的還是舊版」。
set -euo pipefail

AGENT_DIR="${AGENT_DIR:-$HOME/.deskbar-agent}"
LABEL="com.deskbar.usagepush"
LOG="${AGENT_LOG:-$HOME/Library/Logs/deskbar-usagepush.log}"
WAIT_SEC="${AGENT_WAIT_SEC:-150}"
FILES=(usage_push_demo.py openai_usage.py antigravity_usage.py cursor_usage.py commandcode_usage.py opencode_go_usage.py)

repo_root="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -d "$AGENT_DIR" ]; then
  echo "找不到 ${AGENT_DIR}（這台 Mac 沒裝推送 agent），略過"
  exit 0
fi

for f in "${FILES[@]}"; do
  cp "$repo_root/tools/$f" "$AGENT_DIR/$f"
done
for f in "${FILES[@]}"; do
  cmp -s "$repo_root/tools/$f" "$AGENT_DIR/$f" || { echo "同步後內容不一致：$f" >&2; exit 1; }
done
echo "已同步 ${#FILES[@]} 個檔到 $AGENT_DIR"

start_line=$(( $(wc -l < "$LOG") + 1 ))
launchctl kickstart -k "gui/$(id -u)/$LABEL"
echo "已重啟 ${LABEL}，等第一次推送（最多 ${WAIT_SEC} 秒）"

deadline=$(( SECONDS + WAIT_SEC ))
while [ "$SECONDS" -lt "$deadline" ]; do
  new_lines="$(tail -n +"$start_line" "$LOG")"
  if printf '%s\n' "$new_lines" | grep -q '回應非預期'; then
    printf '%s\n' "$new_lines" | grep '回應非預期' | tail -1 >&2
    echo "推送被 deskbar 拒收" >&2
    exit 1
  fi
  if printf '%s\n' "$new_lines" | grep -qE '^(已抓取並推送|已補送快取)'; then
    printf '%s\n' "$new_lines" | grep -E '^(已抓取並推送|已補送快取)' | tail -1 | cut -c1-80
    echo "推送成功"
    exit 0
  fi
  sleep 5
done
echo "${WAIT_SEC} 秒內沒看到推送成功，請看 $LOG" >&2
exit 1
