import os
import re
import threading
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, request

from deskbar import auth, config
from deskbar.claudeusage import UsageInfo

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_USAGE_TZ = ZoneInfo("Asia/Taipei")
_PCT_FIELDS = ("session_pct", "weekly_pct", "fable_pct")
_RESETS_FIELDS = ("session_resets_at", "weekly_resets_at", "fable_resets_at")


def _valid_pct(v) -> bool:
    if v is None:
        return True
    if isinstance(v, bool):
        return False
    if not isinstance(v, (int, float)):
        return False
    return 0 <= v <= 100


def _valid_resets_at(v) -> bool:
    if v is None:
        return True
    if not isinstance(v, str):
        return False
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _parse_dt(v):
    return None if v is None else datetime.fromisoformat(v.replace("Z", "+00:00"))


def _to_float(v):
    return None if v is None else float(v)


def create_app(store, settings_provider=None, settings_lock=None, on_save=None,
              usage_state=None) -> Flask:
    app = Flask("deskbar")
    web_dir = Path(__file__).parent / "web"

    def _calendars_available() -> bool:
        return settings_provider is not None and settings_lock is not None \
            and on_save is not None

    @app.get("/")
    def index():
        return web_dir.joinpath("index.html").read_text(encoding="utf-8")

    @app.get("/api/alarms")
    def list_alarms():
        return jsonify([asdict(a) for a in store.list()])

    @app.post("/api/alarms")
    def add_alarm():
        d = request.get_json(force=True, silent=True) or {}
        time_s, days, label = d.get("time", ""), d.get("days", []), str(d.get("label", ""))[:40]
        if not isinstance(time_s, str) or not _TIME_RE.match(time_s) or not isinstance(days, list) \
                or any((not isinstance(x, int)) or isinstance(x, bool) or x < 0 or x > 6 for x in days):
            return jsonify({"error": "invalid time or days"}), 400
        a = store.add(time_s, days, label or "提醒")
        return jsonify(asdict(a)), 201

    @app.patch("/api/alarms/<aid>")
    def patch_alarm(aid):
        d = request.get_json(force=True, silent=True) or {}
        if not isinstance(d.get("enabled"), bool):
            return jsonify({"error": "enabled must be boolean"}), 400
        if store.set_enabled(aid, d.get("enabled")):
            return jsonify({"ok": True})
        return jsonify({"error": "not found"}), 404

    @app.delete("/api/alarms/<aid>")
    def delete_alarm(aid):
        if store.remove(aid):
            return "", 204
        return jsonify({"error": "not found"}), 404

    @app.get("/api/calendars")
    def list_calendars():
        if not _calendars_available():
            return jsonify({"error": "not available"}), 501
        summaries_by_email: dict[str, dict[str, str]] = {}
        for tok_acc in auth.load_accounts(config.accounts_dir()):
            summaries_by_email[tok_acc["email"]] = {
                cal["id"]: cal.get("summary", cal["id"])
                for cal in tok_acc.get("calendars", [])
            }
        with settings_lock:
            result = []
            for email, acc in settings_provider.accounts.items():
                summaries = summaries_by_email.get(email, {})
                result.append({
                    "account": email,
                    "lane_label": acc.lane_label,
                    "calendars": [
                        {"id": cid, "summary": summaries.get(cid, cid), "enabled": enabled}
                        for cid, enabled in acc.calendars.items()
                    ],
                })
        return jsonify(result)

    @app.patch("/api/calendars")
    def patch_calendar():
        if not _calendars_available():
            return jsonify({"error": "not available"}), 501
        d = request.get_json(force=True, silent=True) or {}
        email, cal_id, enabled = d.get("account"), d.get("calendar_id"), d.get("enabled")
        if not isinstance(enabled, bool):
            return jsonify({"error": "enabled must be boolean"}), 400
        with settings_lock:
            acc = settings_provider.accounts.get(email)
            if acc is None or cal_id not in acc.calendars:
                return jsonify({"error": "not found"}), 404
            acc.calendars[cal_id] = enabled
            on_save(settings_provider)
        return jsonify({"ok": True})

    # 手機網頁可調的裝置偏好（2026-07-27 需求：「那些設定也應該要可以在手機
    # 設定頁調整」）。theme 刻意不開放——theme.set_theme 會清渲染快取，只能由
    # UI 執行緒自己做，webserver 執行緒碰了會跟 render 撞快取。
    _PREF_INT = {
        "work_start_min": (0, 1410), "work_end_min": (0, 1410),
        "brightness_day": (10, 100), "brightness_night": (10, 100),
        "presence_interval_sec": (5, 600), "presence_grace_sec": (0, 3600),
        "sync_interval_min": (1, 120),
    }
    _PREF_BOOL = {"presence_enabled"}

    @app.get("/api/prefs")
    def get_prefs():
        if not _calendars_available():
            return jsonify({"error": "not available"}), 501
        with settings_lock:
            out = {k: getattr(settings_provider, k) for k in _PREF_INT}
            out.update({k: getattr(settings_provider, k) for k in _PREF_BOOL})
        return jsonify(out)

    @app.patch("/api/prefs")
    def patch_prefs():
        if not _calendars_available():
            return jsonify({"error": "not available"}), 501
        d = request.get_json(force=True, silent=True) or {}
        if not isinstance(d, dict) or not d:
            return jsonify({"error": "empty payload"}), 400
        staged = {}
        for k, v in d.items():
            if k in _PREF_BOOL:
                if not isinstance(v, bool):
                    return jsonify({"error": f"{k} must be boolean"}), 400
                staged[k] = v
            elif k in _PREF_INT:
                lo, hi = _PREF_INT[k]
                if not isinstance(v, int) or isinstance(v, bool) or not (lo <= v <= hi):
                    return jsonify({"error": f"{k} out of range {lo}..{hi}"}), 400
                staged[k] = v
            else:
                return jsonify({"error": f"unknown field {k}"}), 400
        with settings_lock:
            for k, v in staged.items():
                setattr(settings_provider, k, v)
            on_save(settings_provider)
        return jsonify({"ok": True})

    @app.post("/api/usage")
    def push_usage():
        """Mac 上的 agent 每 60 秒讀本機 Keychain 的 Claude Code 憑證、打 usage
        API，主動 POST 這支端點推 usage 過來——deskbar 本身不再持有任何憑證、
        不對外發任何請求（見 deskbar.claudeusage 檔頭說明）。跟 /api/alarms 一樣
        在區網/tailnet 內預設無認證；設了 DESKBAR_PUSH_TOKEN 環境變數才要求
        X-Deskbar-Token 相符，避免同網段裝置誤打這支端點污染畫面。"""
        if usage_state is None:
            return jsonify({"error": "not available"}), 501
        push_token = os.environ.get("DESKBAR_PUSH_TOKEN")
        if push_token and request.headers.get("X-Deskbar-Token") != push_token:
            return jsonify({"error": "unauthorized"}), 401

        d = request.get_json(force=True, silent=True)
        if not isinstance(d, dict):
            return jsonify({"error": "body must be a JSON object"}), 400
        for f in _PCT_FIELDS:
            if not _valid_pct(d.get(f)):
                return jsonify({"error": f"invalid {f}"}), 400
        for f in _RESETS_FIELDS:
            if not _valid_resets_at(d.get(f)):
                return jsonify({"error": f"invalid {f}"}), 400

        info = UsageInfo(
            session_pct=_to_float(d.get("session_pct")),
            session_resets_at=_parse_dt(d.get("session_resets_at")),
            weekly_pct=_to_float(d.get("weekly_pct")),
            weekly_resets_at=_parse_dt(d.get("weekly_resets_at")),
            fable_pct=_to_float(d.get("fable_pct")),
            fable_resets_at=_parse_dt(d.get("fable_resets_at")),
            fetched_at=datetime.now(_USAGE_TZ),
        )
        usage_state.set_usage(info)
        return "", 204

    return app


def start_web(store, port: int = 8080, settings_provider=None, settings_lock=None,
              on_save=None, usage_state=None) -> None:
    app = create_app(store, settings_provider=settings_provider, settings_lock=settings_lock,
                      on_save=on_save, usage_state=usage_state)
    t = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False),
        daemon=True)
    t.start()
