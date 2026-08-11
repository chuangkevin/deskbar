#!/bin/bash
set -euo pipefail

# Pure observer script for Pi side network connectivity.
# Strictly read-only: no nmcli connection up, no radio restart, no systemctl, no sudo.

# Deliberately independent of the private Tailnet / reverse-proxy path.  This
# only tests whether the Pi's configured resolver can answer a public name.
DNS_HOST="${DESKBAR_OBSERVER_DNS_HOST:-connectivitycheck.gstatic.com}"
PUBLIC_URL="${DESKBAR_OBSERVER_PUBLIC_URL:-http://1.1.1.1}"
LOCAL_URL="${DESKBAR_OBSERVER_LOCAL_URL:-http://127.0.0.1:8080}"

STATE_DIR="${RUNTIME_DIRECTORY:-${DESKBAR_OBSERVER_RUN_DIR:-/run/deskbar-net-observer}}"
mkdir -p "$STATE_DIR" 2>/dev/null || true
STATE_FILE="$STATE_DIR/state"

# 1. wlan0_connected
wlan0_connected="false"
if nmcli -t -f DEVICE,STATE dev 2>/dev/null | grep -q "^wlan0:connected"; then
    wlan0_connected="true"
fi

# 2. route_via_wlan0
route_via_wlan0="false"
if ip route 2>/dev/null | grep -q "^default.*dev wlan0"; then
    route_via_wlan0="true"
fi

# 3. dns_resolution
dns_resolution="false"
if getent hosts "$DNS_HOST" >/dev/null 2>&1; then
    dns_resolution="true"
fi

# 4. public_ip_http
public_ip_http="false"
# `route_via_wlan0` above proves the default route.  Do not use curl's
# --interface here: binding a device needs privileges on some Pi OS releases
# and would turn a healthy connection into a false negative.
if curl -sS --connect-timeout 3 -m 5 -o /dev/null "$PUBLIC_URL" 2>/dev/null; then
    public_ip_http="true"
fi

# 5. deskbar_local_http
deskbar_local_http="false"
if curl -s -m 3 -o /dev/null "$LOCAL_URL" 2>/dev/null; then
    deskbar_local_http="true"
fi

CURRENT_STATE="wlan0_connected=$wlan0_connected route_via_wlan0=$route_via_wlan0 dns_resolution=$dns_resolution public_ip_http=$public_ip_http deskbar_local_http=$deskbar_local_http"

PREV_STATE=""
if [ -f "$STATE_FILE" ]; then
    PREV_STATE=$(cat "$STATE_FILE" 2>/dev/null || true)
fi

if [ "$CURRENT_STATE" != "$PREV_STATE" ]; then
    logger -t deskbar-net-observer "$CURRENT_STATE" 2>/dev/null || printf "deskbar-net-observer: %s\n" "$CURRENT_STATE"
    printf "%s\n" "$CURRENT_STATE" > "$STATE_FILE"
fi
