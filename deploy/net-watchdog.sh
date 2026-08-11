#!/bin/bash
# deskbar 連線看門狗 v3
# 
# 歷史教訓：
# v1 用 ping gateway 判斷，在 Android 熱點不回 ICMP 時會變成每分鐘把好好的 WiFi 關開一輪、自己製造無限斷線。
# v2 改以 NetworkManager 裝置狀態 wlan0 判斷，把窗口放寬到 2 分鐘，但誤認為「未達 connected」就是死線，
# 會在 NM 正在重連的漫長過程中（disconnected → prepare → config → need-auth → ip-config）將其攔腰打斷。
# 2026-08-07 事故中，實機被此腳本觸發了 1758 次 radio 關開，導致 3 天斷線，因為在公司壅塞的 2.4G 環境
# 跑完完整重連要超過 2 分鐘，舊版每 2 分鐘就再踢一次，NM 永遠沒機會跑完整套流程。
# 
# v3 邏輯：
# 1. 偵測三態（CONNECTED / PROGRESSING / DEAD）
# 2. 如果是 PROGRESSING，NM 正在努力，絕對不要碰它，清除計數並退出。
# 3. 連續 FAIL_THRESHOLD 輪（每輪由 timer 觸發約 1 分鐘，預設 5 分鐘）皆為 DEAD，才開始動作。
# 4. 動作分段：先溫和（請 NM 自己連已知設定檔），失敗才強硬（踢 radio）。
# 5. 動作完成後退避 COOLDOWN_S 秒（10 分鐘），避免打斷 NM 的重連。

set -u

FAIL_FILE="${DESKBAR_WATCHDOG_FAIL_FILE:-/run/deskbar-watchdog.fail}"
COOLDOWN_FILE="${DESKBAR_WATCHDOG_COOLDOWN_FILE:-/run/deskbar-watchdog.cooldown}"
STATE_FILE="${DESKBAR_WATCHDOG_STATE_FILE:-/run/deskbar-watchdog.state}"
ACTION_FILE="${DESKBAR_WATCHDOG_ACTION_FILE:-/run/deskbar-watchdog.actions}"
FAIL_THRESHOLD="${DESKBAR_WATCHDOG_FAIL_THRESHOLD:-5}" # 2026-08-07 實測重連需時較長，連續 5 輪 DEAD 才能動作
COOLDOWN_S="${DESKBAR_WATCHDOG_COOLDOWN_S:-600}"
ACTION_WINDOW_S="${DESKBAR_WATCHDOG_ACTION_WINDOW_S:-3600}"

log() {
    logger -t deskbar-watchdog "$*"
}

summarize_states() {
    summary=$(printf '%s' "$1" | tr '\n' ' ' | sed 's/[[:space:]]*$//')
    if [ -n "$summary" ]; then
        printf '%s' "$summary"
    else
        printf '<empty>'
    fi
}

record_state_transition() {
    state="$1"
    nmcli_rc="$2"
    summary="$3"
    marker="${state}|${nmcli_rc}|${summary}"
    previous=$(cat "$STATE_FILE" 2>/dev/null || true)
    if [ "$previous" != "$marker" ]; then
        printf '%s\n' "$marker" > "$STATE_FILE" 2>/dev/null || true
        log "狀態轉換 state=$state nmcli_rc=$nmcli_rc summary=$summary"
    fi
}

record_radio_action() {
    action_now=$(date +%s)
    cutoff=$((action_now - ACTION_WINDOW_S))
    tmp="${ACTION_FILE}.$$"
    {
        if [ -f "$ACTION_FILE" ]; then
            while IFS=' ' read -r ts kind; do
                case "$ts" in
                    ''|*[!0-9]*) continue ;;
                esac
                if [ "$ts" -ge "$cutoff" ]; then
                    printf '%s %s\n' "$ts" "$kind"
                fi
            done < "$ACTION_FILE"
        fi
        printf '%s radio_restart\n' "$action_now"
    } > "$tmp" 2>/dev/null || true
    if [ -f "$tmp" ]; then
        mv "$tmp" "$ACTION_FILE" 2>/dev/null || true
    fi
    action_count=$(wc -l < "$ACTION_FILE" 2>/dev/null | tr -d ' ')
    if [ -z "$action_count" ]; then
        action_count=1
    fi
    printf '%s' "$action_count"
}

# 檢查冷卻中
if [ -f "$COOLDOWN_FILE" ]; then
    cooldown_ts=$(cat "$COOLDOWN_FILE" 2>/dev/null || echo 0)
    now=$(date +%s)
    if [ $((now - cooldown_ts)) -lt $COOLDOWN_S ]; then
        exit 0
    fi
fi

STATES=$(nmcli -t -f DEVICE,STATE dev 2>&1)
nmcli_rc=$?
if [ "$nmcli_rc" -ne 0 ]; then
    raw_error=$(summarize_states "$STATES")
    log "nmcli 裝置狀態讀取失敗 rc=${nmcli_rc} output=${raw_error}；本輪沿用 DEAD 路徑但保留錯誤碼"
    STATES=""
fi
summary=$(summarize_states "$STATES")
# 因為 STATES 內容含有換行，使用 grep 進行多行比對

# 判斷是否 CONNECTED：任一 wlan0|usb*|eth* 介面是 connected
if [ "$nmcli_rc" -eq 0 ] && echo "$STATES" | grep -qE '^(wlan0|usb[0-9]*|eth[0-9]*):connected$'; then
    record_state_transition "CONNECTED" "$nmcli_rc" "$summary"
    rm -f "$FAIL_FILE"
    exit 0
fi

# 判斷是否 PROGRESSING：介面正在重連中
if [ "$nmcli_rc" -eq 0 ] && echo "$STATES" | grep -qE '^(wlan0|usb[0-9]*|eth[0-9]*):(connecting|prepare|config|need-auth|ip-config|ip-check|secondaries)'; then
    # NM 正在努力，絕對不要碰它
    record_state_transition "PROGRESSING" "$nmcli_rc" "$summary"
    rm -f "$FAIL_FILE"
    exit 0
fi

# 狀態為 DEAD，累加失敗計數
fails=$(cat "$FAIL_FILE" 2>/dev/null || echo 0)
fails=$((fails + 1))
echo "$fails" > "$FAIL_FILE"

record_state_transition "DEAD" "$nmcli_rc" "$summary"
log "連線狀態 DEAD (${fails}/${FAIL_THRESHOLD})。nmcli_rc=${nmcli_rc} 當前狀態摘要: ${summary}"

if [ "$fails" -lt "$FAIL_THRESHOLD" ]; then
    exit 0
fi

# 達到門檻，開始動作，清除計數
rm -f "$FAIL_FILE"

log "達到失敗門檻，開始執行第一段(溫和)救援：嘗試喚醒現有設定檔"

# 取得 802-11-wireless 的連線清單
connections=$(nmcli -t -f NAME,TYPE connection show 2>/dev/null | grep ':802-11-wireless$' | sed 's/:802-11-wireless$//' || true)
success=0
profile_count=$(printf '%s\n' "$connections" | sed '/^$/d' | wc -l | tr -d ' ')
log "第一段救援候選 WiFi profile 數量=${profile_count}"

if [ -n "$connections" ]; then
    while IFS= read -r conn; do
        if [ -n "$conn" ]; then
            # nmcli connection up 預設等 90 秒，三個 profile 輪完最壞 4 分半，會讓看門狗單輪過長；限制成 25 秒，連得上的情境通常 10 秒內就好，連不上就快點讓位給第二段。
            conn_start=$(date +%s)
            if nmcli -w 25 connection up id "$conn" 2>/dev/null; then
                success=1
                conn_elapsed=$(($(date +%s) - conn_start))
                log "成功啟動連線 ${conn}，結束第一段救援，耗時=${conn_elapsed}s"
                break
            else
                conn_rc=$?
                conn_elapsed=$(($(date +%s) - conn_start))
                log "啟動連線 ${conn} 失敗 rc=${conn_rc} 耗時=${conn_elapsed}s"
            fi
        fi
    done <<< "$connections"
fi

if [ "$success" -eq 0 ]; then
    action_count=$(record_radio_action)
    log "第一段救援失敗，執行第二段(強硬)救援：重啟 WiFi radio；近 ${ACTION_WINDOW_S} 秒 radio_restart 次數=${action_count}"
    nmcli radio wifi off 2>/dev/null || true
    sleep 5
    nmcli radio wifi on 2>/dev/null || true
fi

# 寫入冷卻戳記
date +%s > "$COOLDOWN_FILE"
log "進入冷卻期 ${COOLDOWN_S} 秒"

exit 0
