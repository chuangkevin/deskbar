import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, request

from deskbar import auth, config
from deskbar.alarms import _is_valid_date_str
from deskbar.claudeusage import UsageInfo
from deskbar.presence import PresenceState
from deskbar.webapi.context import WebContext
from deskbar.webapi.validation import (
    _PCT_FIELDS,
    _PREF_BOOL,
    _PREF_FLOAT,
    _PREF_INT,
    _PREF_STR,
    _RESETS_FIELDS,
    _TIME_RE,
    _USAGE_FETCHED_FIELDS,
    _USAGE_TZ,
    _parse_dt,
    _to_float,
    _valid_pct,
    _valid_resets_at,
)

_WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def register_routes(app: Flask, context: WebContext) -> None:
    """Registers all endpoint handlers on the Flask app using WebContext."""

    @app.get("/")
    def index():
        return _WEB_DIR.joinpath("index.html").read_text(encoding="utf-8")

    @app.get("/api/alarms")
    def list_alarms():
        return jsonify([asdict(a) for a in context.store.list()])

    @app.post("/api/alarms")
    def add_alarm():
        d = request.get_json(force=True, silent=True) or {}
        time_s, days, label = d.get("time", ""), d.get("days", []), str(d.get("label", ""))[:40]
        if not isinstance(time_s, str) or not _TIME_RE.match(time_s) or not isinstance(days, list) \
                or any((not isinstance(x, int)) or isinstance(x, bool) or x < 0 or x > 6 for x in days):
            return jsonify({"error": "invalid time or days"}), 400
        a = context.store.add(time_s, days, label or "提醒")
        return jsonify(asdict(a)), 201

    @app.patch("/api/alarms/<aid>")
    def patch_alarm(aid):
        d = request.get_json(force=True, silent=True) or {}
        has_enabled = "enabled" in d
        has_skip_date = "skip_date" in d
        if not has_enabled and not has_skip_date:
            return jsonify({"error": "enabled or skip_date required"}), 400

        if has_enabled and not isinstance(d.get("enabled"), bool):
            return jsonify({"error": "enabled must be boolean"}), 400

        if has_skip_date:
            skip_date = d.get("skip_date")
            if skip_date is not None and not _is_valid_date_str(skip_date):
                return jsonify({"error": "skip_date must be YYYY-MM-DD or null"}), 400

        existing = next((a for a in context.store.list() if a.id == aid), None)
        if existing is None:
            return jsonify({"error": "not found"}), 404

        if has_enabled:
            context.store.set_enabled(aid, d["enabled"])
        if has_skip_date:
            context.store.set_skip_date(aid, d["skip_date"])

        return jsonify({"ok": True})

    @app.delete("/api/alarms/<aid>")
    def delete_alarm(aid):
        if context.store.remove(aid):
            return "", 204
        return jsonify({"error": "not found"}), 404

    @app.get("/api/calendars")
    def list_calendars():
        if not context.calendars_available:
            return jsonify({"error": "not available"}), 501
        summaries_by_email: dict[str, dict[str, str]] = {}
        for tok_acc in auth.load_accounts(config.accounts_dir()):
            summaries_by_email[tok_acc["email"]] = {
                cal["id"]: cal.get("summary", cal["id"])
                for cal in tok_acc.get("calendars", [])
            }
        with context.settings_lock:
            result = []
            for email, acc in context.settings_provider.accounts.items():
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
        if not context.calendars_available:
            return jsonify({"error": "not available"}), 501
        d = request.get_json(force=True, silent=True) or {}
        email, cal_id, enabled = d.get("account"), d.get("calendar_id"), d.get("enabled")
        if not isinstance(enabled, bool):
            return jsonify({"error": "enabled must be boolean"}), 400
        with context.settings_lock:
            acc = context.settings_provider.accounts.get(email)
            if acc is None or cal_id not in acc.calendars:
                return jsonify({"error": "not found"}), 404
            acc.calendars[cal_id] = enabled
            context.on_save(context.settings_provider)
        return jsonify({"ok": True})

    @app.get("/api/notes")
    def list_notes():
        if context.notes_store is None:
            return jsonify({"error": "not available"}), 501
        return jsonify([asdict(n) for n in context.notes_store.list()])

    def _notes_changed():
        # 便條變更後叫醒裝置的 render 迴圈（usage_state 即 AppState），
        # 便條牆才會即時跟上，不用等下一次整分重繪。
        if context.usage_state is not None:
            context.usage_state.bump()

    @app.post("/api/notes")
    def add_note():
        """便條輸入端（Mac shell function／手機網頁）。跟 /api/alarms 一樣
        tailnet 內無認證；文字上限由 NotesStore 截斷。"""
        if context.notes_store is None:
            return jsonify({"error": "not available"}), 501
        d = request.get_json(force=True, silent=True) or {}
        n = context.notes_store.add(d.get("text", "") if isinstance(d.get("text"), str) else "")
        if n is None:
            return jsonify({"error": "text required"}), 400
        _notes_changed()
        return jsonify(asdict(n)), 201

    @app.patch("/api/notes/<nid>")
    def patch_note(nid):
        """改內文和/或顏色（color -1=自動輪色、0..4=色盤索引）。"""
        if context.notes_store is None:
            return jsonify({"error": "not available"}), 501
        d = request.get_json(force=True, silent=True) or {}
        text = d.get("text")
        color = d.get("color")
        if text is None and color is None:
            return jsonify({"error": "text or color required"}), 400
        if text is not None and (not isinstance(text, str) or not text.strip()):
            return jsonify({"error": "text required"}), 400
        if color is not None and (not isinstance(color, int)
                                  or isinstance(color, bool)
                                  or not (-1 <= color <= 4)):
            return jsonify({"error": "color must be -1..4"}), 400
        n = context.notes_store.patch(nid, text=text, color=color)
        if n is None:
            return jsonify({"error": "not found"}), 404
        _notes_changed()
        return jsonify(asdict(n))

    @app.post("/api/notes/reorder")
    def reorder_notes():
        """整批重排（拖曳放手後送完整 id 順序，冪等、不怕連拖多次）。"""
        if context.notes_store is None:
            return jsonify({"error": "not available"}), 501
        d = request.get_json(force=True, silent=True) or {}
        ids = d.get("order")
        if not isinstance(ids, list) or len(ids) > 100 \
                or not all(isinstance(x, str) for x in ids):
            return jsonify({"error": "order must be a list of note ids"}), 400
        if context.notes_store.reorder(ids):
            _notes_changed()
        return jsonify({"ok": True})

    @app.delete("/api/notes/<nid>")
    def delete_note(nid):
        if context.notes_store is None:
            return jsonify({"error": "not available"}), 501
        if context.notes_store.remove(nid):
            _notes_changed()
            return "", 204
        return jsonify({"error": "not found"}), 404

    @app.get("/api/prefs")
    def get_prefs():
        if not context.calendars_available:
            return jsonify({"error": "not available"}), 501
        with context.settings_lock:
            out = {k: getattr(context.settings_provider, k) for k in _PREF_INT}
            out.update({k: getattr(context.settings_provider, k) for k in _PREF_BOOL})
            # 祕密欄位只回「是否已設定」，原文永不出站
            out["linear_key_set"] = bool(getattr(context.settings_provider,
                                                 "linear_api_key", ""))
            out["weather_label"] = getattr(context.settings_provider, "weather_label", "")
            out["weather_metar_station"] = getattr(context.settings_provider, "weather_metar_station", "RCSS")
            out["scene_mode"] = getattr(context.settings_provider, "scene_mode", "auto")
            out["scenes_enabled"] = list(getattr(context.settings_provider,
                                                 "scenes_enabled", []))
            out["presence_source"] = getattr(context.settings_provider, "presence_source", "bluetooth")
            out["usage_sources"] = list(getattr(context.settings_provider, "usage_sources",
                                                   config.VALID_USAGE_SOURCES))
        return jsonify(out)

    @app.patch("/api/prefs")
    def patch_prefs():
        if not context.calendars_available:
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
            elif k in _PREF_STR:
                if not isinstance(v, str) or len(v) > _PREF_STR[k]:
                    return jsonify({"error": f"{k} must be string"}), 400
                staged[k] = v.strip()
            elif k == "scene_mode":
                if v not in ("auto", "manual", "force"):
                    return jsonify({"error": "scene_mode must be auto/manual/force"}), 400
                staged[k] = v
            elif k == "presence_source":
                if v not in ("bluetooth", "push", "ble"):
                    return jsonify({"error": "presence_source must be bluetooth, push, or ble"}), 400
                staged[k] = v
            elif k == "scenes_enabled":
                from deskbar.config import SCENE_KEYS
                if not isinstance(v, list) or not all(
                        isinstance(x, str) and x in SCENE_KEYS for x in v):
                    return jsonify({"error": "scenes_enabled has unknown scene"}), 400
                # 保序去重；全反勾退回全部（空清單無意義，config 同一約定）
                staged[k] = tuple(k2 for k2 in SCENE_KEYS if k2 in v) or SCENE_KEYS
            elif k == "usage_sources":
                if not isinstance(v, list) or not all(
                        isinstance(x, str) and x in config.VALID_USAGE_SOURCES for x in v):
                    return jsonify({"error": "usage_sources has unknown source"}), 400
                staged[k] = config.normalize_usage_sources(v)
            elif k in _PREF_FLOAT:
                lo, hi = _PREF_FLOAT[k]
                if isinstance(v, bool) or not isinstance(v, (int, float)) \
                        or not (lo <= v <= hi):
                    return jsonify({"error": f"{k} out of range"}), 400
                staged[k] = float(v)
            else:
                return jsonify({"error": f"unknown field {k}"}), 400
        with context.settings_lock:
            for k, v in staged.items():
                setattr(context.settings_provider, k, v)
            context.on_save(context.settings_provider)
        if context.usage_state is not None:
            context.usage_state.bump()   # 叫醒 render 迴圈：亮度/睡眠等改動即時上畫面
        if staged.keys() & {"weather_lat", "weather_lon", "weather_label",
                            "weather_auto_locate", "weather_metar_station"}:
            try:
                from deskbar import sync as _sync
                _sync.FORCE_WX.set()   # 位置改了立刻重抓天氣，不等下一小時
            except Exception:
                pass
        return jsonify({"ok": True})

    @app.get("/api/screenshot")
    def screenshot():
        """目前螢幕畫面（PNG，未疊亮度黑幕的邏輯畫面）。遠端支援神器：
        回報問題不用再拍螢幕，直接抓這支。走 want/done 事件橋請 render
        執行緒代拍——pygame Surface 不能跨執行緒碰。"""
        if context.shot_bridge is None:
            return jsonify({"error": "not available"}), 501
        with context.shot_lock:
            context.shot_bridge["done"].clear()
            context.shot_bridge["data"] = None
            context.shot_bridge["want"].set()
            if not context.shot_bridge["done"].wait(3.0):
                context.shot_bridge["want"].clear()
                return jsonify({"error": "render loop timeout"}), 504
            data = context.shot_bridge["data"]
        if not data:
            return jsonify({"error": "capture failed"}), 500
        return Response(data, mimetype="image/png")

    @app.get("/api/backup")
    def backup():
        """設定備份下載（SD 卡是 Pi 的頭號死因）。打包 settings/alarms/notes
        三份 JSON；linear_api_key 刻意剔除——備份檔會落到手機下載夾，
        祕密不出站（比照 /api/prefs 的 linear_key_set 原則）。"""
        import json as _json
        cfgd = config.config_dir()
        out = {"exported_at": datetime.now(_USAGE_TZ).isoformat(),
               "settings": None, "alarms": None, "notes": None}
        for key, fn in (("settings", "settings.json"), ("alarms", "alarms.json"),
                        ("notes", "notes.json")):
            try:
                out[key] = _json.loads((cfgd / fn).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        if isinstance(out["settings"], dict):
            out["settings"].pop("linear_api_key", None)
        resp = jsonify(out)
        resp.headers["Content-Disposition"] = \
            "attachment; filename=deskbar-backup.json"
        return resp

    @app.post("/api/presence")
    def push_presence():
        """外部主動推送在場狀態（iPhone 捷徑自動化／外部感測器）。
        2026-08-04 實機事故擴充：iPhone 藍牙對 L2CAP echo 不回應且 MAC 隨機化，
        對藍牙探測本質不可靠。提供推送端點讓手機端主動報到。

        與 /api/usage 同樣原則：Tailnet 內預設無認證，若環境變數 DESKBAR_PUSH_TOKEN
        有設則驗證 X-Deskbar-Token 標頭。
        """
        if context.usage_state is None:
            return jsonify({"error": "not available"}), 501
        push_token = os.environ.get("DESKBAR_PUSH_TOKEN")
        if push_token and request.headers.get("X-Deskbar-Token") != push_token:
            return jsonify({"error": "unauthorized"}), 401

        d = request.get_json(force=True, silent=True)
        if not isinstance(d, dict):
            return jsonify({"error": "body must be a JSON object"}), 400

        if "present" not in d or not isinstance(d["present"], bool):
            return jsonify({"error": "invalid present"}), 400

        present = d["present"]
        rssi = d.get("rssi")
        if rssi is not None and (not isinstance(rssi, int) or isinstance(rssi, bool)):
            return jsonify({"error": "invalid rssi"}), 400

        enabled = True
        if context.settings_provider is not None and context.settings_lock is not None:
            with context.settings_lock:
                enabled = getattr(context.settings_provider, "presence_enabled", True)

        prev = context.usage_state.snapshot().presence
        now = datetime.now(_USAGE_TZ)
        last_seen = now if present else prev.last_seen

        context.usage_state.set_presence(PresenceState(present=present, rssi=rssi,
                                               last_seen=last_seen, enabled=enabled))
        return "", 204

    @app.post("/api/usage")
    def push_usage():
        """Mac agent 定期讀本機 Claude Code 憑證並把 usage 快照推到這支端點。

        Agent 可重送本機快取；fetched_at 保留原始抓取時間，避免重送舊快取時把資料
        偽裝成新鮮。deskbar 本身不持有任何憑證、
        不對外發任何請求（見 deskbar.claudeusage 檔頭說明）。跟 /api/alarms 一樣
        在區網/tailnet 內預設無認證；設了 DESKBAR_PUSH_TOKEN 環境變數才要求
        X-Deskbar-Token 相符，避免同網段裝置誤打這支端點污染畫面。"""
        if context.usage_state is None:
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
        for f in _USAGE_FETCHED_FIELDS:
            if f in d and not _valid_resets_at(d.get(f)):
                return jsonify({"error": f"invalid {f}"}), 400

        fetched_at = _parse_dt(d.get("fetched_at")) \
            if d.get("fetched_at") is not None else datetime.now(_USAGE_TZ)
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=_USAGE_TZ)

        def _optional_fetched(field):
            value = _parse_dt(d.get(field))
            return value.replace(tzinfo=_USAGE_TZ) if value is not None and value.tzinfo is None else value

        info = UsageInfo(
            session_pct=_to_float(d.get("session_pct")),
            session_resets_at=_parse_dt(d.get("session_resets_at")),
            weekly_pct=_to_float(d.get("weekly_pct")),
            weekly_resets_at=_parse_dt(d.get("weekly_resets_at")),
            fable_pct=_to_float(d.get("fable_pct")),
            fable_resets_at=_parse_dt(d.get("fable_resets_at")),
            fetched_at=fetched_at,
            ag_5h_pct=_to_float(d.get("ag_5h_pct")),
            ag_5h_resets_at=_parse_dt(d.get("ag_5h_resets_at")),
            ag_weekly_pct=_to_float(d.get("ag_weekly_pct")),
            ag_weekly_resets_at=_parse_dt(d.get("ag_weekly_resets_at")),
            oa_weekly_pct=_to_float(d.get("oa_weekly_pct")),
            oa_weekly_resets_at=_parse_dt(d.get("oa_weekly_resets_at")),
            claude_fetched_at=_optional_fetched("claude_fetched_at"),
            ag_fetched_at=_optional_fetched("ag_fetched_at"),
            oa_fetched_at=_optional_fetched("oa_fetched_at"),
        )
        context.usage_state.set_usage(info)
        return "", 204
