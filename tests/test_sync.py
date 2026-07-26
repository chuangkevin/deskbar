import json
from datetime import date, datetime
from zoneinfo import ZoneInfo
from deskbar import sync
from deskbar.config import Settings
from deskbar.store import AppState
from deskbar.auth import AuthError

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 7, 27, 12, 0, tzinfo=TZ)


def _acc_file(dir, email="a@x.com"):
    (dir / f"{email}.json").write_text(json.dumps({
        "email": email, "refresh_token": "rt", "client_id": "c", "client_secret": "s",
        "calendars": [{"id": email, "summary": "主要", "primary": True}],
    }), encoding="utf-8")


def _deps(monkeypatch, tmp_path, fetch_result):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("DESKBAR_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(sync, "_get_token", lambda acc, http_post: "tok")
    monkeypatch.setattr(sync, "_fetch_range",
                        lambda tok, cal, start, end, tz, http_get: fetch_result(cal))
    return sync.SyncDeps(today_fn=lambda: date(2026, 7, 27), now_fn=lambda: NOW,
                         http_get=None, http_post=None, tz=TZ)


def test_new_account_registered_and_synced(tmp_path, monkeypatch):
    from deskbar import config as cfg
    deps = _deps(monkeypatch, tmp_path, lambda cal: [{
        "id": "e1", "summary": "會", "status": "confirmed",
        "start": {"dateTime": "2026-07-27T02:00:00Z"},
        "end": {"dateTime": "2026-07-27T03:00:00Z"}}])
    _acc_file(cfg.accounts_dir())
    state, settings = AppState(), Settings()
    sync.calendar_sync_once(state, settings, deps)
    snap = state.snapshot()
    assert "a@x.com" in settings.accounts
    assert settings.accounts["a@x.com"].calendars == {"a@x.com": True}
    assert len(snap.events) == 1 and snap.statuses["a@x.com"].ok


def test_auth_error_marks_account(tmp_path, monkeypatch):
    from deskbar import config as cfg

    def boom(tok, cal, start, end, tz, http_get):
        raise AuthError("bad")

    deps = _deps(monkeypatch, tmp_path, None)
    monkeypatch.setattr(sync, "_fetch_range", boom)
    _acc_file(cfg.accounts_dir())
    state, settings = AppState(), Settings()
    sync.calendar_sync_once(state, settings, deps)
    st = state.snapshot().statuses["a@x.com"]
    assert st.ok is False and st.error == "需重新授權"


def test_removed_account_dropped(tmp_path, monkeypatch):
    from deskbar import config as cfg
    deps = _deps(monkeypatch, tmp_path, lambda cal: [])
    _acc_file(cfg.accounts_dir())
    state, settings = AppState(), Settings()
    sync.calendar_sync_once(state, settings, deps)
    (cfg.accounts_dir() / "a@x.com.json").unlink()
    sync.calendar_sync_once(state, settings, deps)
    assert "a@x.com" not in state.snapshot().statuses
