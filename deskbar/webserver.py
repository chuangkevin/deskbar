import re
import threading
from dataclasses import asdict
from pathlib import Path

from flask import Flask, jsonify, request

from deskbar import auth, config

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def create_app(store, settings_provider=None, settings_lock=None, on_save=None) -> Flask:
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

    return app


def start_web(store, port: int = 8080, settings_provider=None, settings_lock=None,
              on_save=None) -> None:
    app = create_app(store, settings_provider=settings_provider, settings_lock=settings_lock,
                      on_save=on_save)
    t = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False),
        daemon=True)
    t.start()
