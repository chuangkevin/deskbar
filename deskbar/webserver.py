import re
import threading
from dataclasses import asdict
from pathlib import Path

from flask import Flask, jsonify, request

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def create_app(store) -> Flask:
    app = Flask("deskbar")
    web_dir = Path(__file__).parent / "web"

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
        if not _TIME_RE.match(time_s) or not isinstance(days, list) \
                or any((not isinstance(x, int)) or x < 0 or x > 6 for x in days):
            return jsonify({"error": "invalid time or days"}), 400
        a = store.add(time_s, days, label or "提醒")
        return jsonify(asdict(a)), 201

    @app.patch("/api/alarms/<aid>")
    def patch_alarm(aid):
        d = request.get_json(force=True, silent=True) or {}
        if store.set_enabled(aid, bool(d.get("enabled"))):
            return jsonify({"ok": True})
        return jsonify({"error": "not found"}), 404

    @app.delete("/api/alarms/<aid>")
    def delete_alarm(aid):
        if store.remove(aid):
            return "", 204
        return jsonify({"error": "not found"}), 404

    return app


def start_web(store, port: int = 8080) -> None:
    app = create_app(store)
    t = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False),
        daemon=True)
    t.start()
