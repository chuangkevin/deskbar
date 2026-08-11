#!/usr/bin/env python3
"""Mac resident net probe for Deskbar & domain HTTP/HTTPS connectivity.

Purely observational probe:
- Default check interval: 15 seconds.
- Checks Pi Tailnet HTTP and desk.sisihome.org HTTPS.
- Writes to log path only when state changes.
- Strictly logs boolean/enum states; no URLs, headers, body, DNS addresses, or tokens.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_PI_TAILNET_URL = "http://100.98.35.59:8080"
DEFAULT_DESK_SISHOME_URL = "https://desk.sisihome.org"
DEFAULT_LOG_PATH = "/tmp/deskbar-net-probe.log"
DEFAULT_INTERVAL = 15.0


def probe_endpoint(url: str, timeout: float = 5.0) -> bool:
    try:
        req = Request(url, method="GET")
        req.add_header("User-Agent", "DeskbarNetProbe/1.0")
        with urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 400 or resp.status in (401, 403, 404)
    except HTTPError:
        # HTTP response status code (e.g. 404, 500) indicates transport layer reached the host
        return True
    except (URLError, OSError, ValueError):
        return False


def format_state(pi_tailnet_http: bool, desk_sisihome_https: bool) -> str:
    pi_str = "true" if pi_tailnet_http else "false"
    sisi_str = "true" if desk_sisihome_https else "false"
    return f"pi_tailnet_http={pi_str} desk_sisihome_https={sisi_str}"


def read_last_state(log_path: Path) -> str | None:
    if not log_path.exists():
        return None
    try:
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        if not lines:
            return None
        last_line = lines[-1]
        if "pi_tailnet_http=" in last_line:
            idx = last_line.find("pi_tailnet_http=")
            return last_line[idx:]
    except (OSError, UnicodeDecodeError):
        return None
    return None


def log_state_change(log_path: Path, state_str: str) -> None:
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log_entry = f"[{now_iso}] {state_str}\n"

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except OSError:
        # Do not include paths or endpoint details here: launchd sends stderr
        # to the same diagnostic file as state changes.
        sys.stderr.write("deskbar-net-probe: unable to append state change\n")


def run_probe(pi_url: str, sisi_url: str, log_path: Path, last_state: str | None) -> str | None:
    pi_ok = probe_endpoint(pi_url)
    sisi_ok = probe_endpoint(sisi_url)
    current_state = format_state(pi_ok, sisi_ok)

    if current_state != last_state:
        log_state_change(log_path, current_state)
        return current_state
    return last_state


def main() -> None:
    parser = argparse.ArgumentParser(description="Deskbar Mac Net Probe")
    parser.add_argument("--once", action="store_true", help="Run probe once and exit")
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL,
        help="Probe interval in seconds (default: 15)",
    )
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be greater than zero")

    pi_url = os.environ.get("PI_TAILNET_URL", DEFAULT_PI_TAILNET_URL)
    sisi_url = os.environ.get("DESK_SISHOME_URL", DEFAULT_DESK_SISHOME_URL)
    log_path = Path(
        os.environ.get(
            "DESKBAR_NET_PROBE_LOG",
            os.environ.get("LOG_PATH", DEFAULT_LOG_PATH),
        )
    )

    last_state = read_last_state(log_path)

    if args.once:
        run_probe(pi_url, sisi_url, log_path, last_state)
        return

    while True:
        last_state = run_probe(pi_url, sisi_url, log_path, last_state)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
