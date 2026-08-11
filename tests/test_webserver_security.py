from deskbar.alarms import AlarmStore
from deskbar.store import AppState
from deskbar.webserver import create_app


def _client(tmp_path, monkeypatch, **kwargs):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    store = AlarmStore()
    store.load()
    app = create_app(store, **kwargs)
    app.config["TESTING"] = True
    return app.test_client(), store


def test_security_headers_on_mobile_page(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)

    r = client.get("/", base_url="http://deskbar.local:8080")

    assert r.status_code == 200
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "same-origin"
    csp = r.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp
    assert "https://geocoding-api.open-meteo.com" in csp


def test_same_origin_unsafe_request_still_allows_mobile_ui(tmp_path, monkeypatch):
    client, store = _client(tmp_path, monkeypatch)

    r = client.post(
        "/api/alarms",
        base_url="http://deskbar.local:8080",
        headers={"Origin": "http://deskbar.local:8080"},
        json={"time": "09:30", "days": [1], "label": "早會"},
    )

    assert r.status_code == 201
    assert len(store.list()) == 1


def test_cross_site_unsafe_request_is_blocked_without_side_effect(tmp_path, monkeypatch):
    client, store = _client(tmp_path, monkeypatch)

    r = client.post(
        "/api/alarms",
        base_url="http://deskbar.local:8080",
        headers={"Origin": "https://evil.example"},
        json={"time": "09:30", "days": [1], "label": "偷塞"},
    )

    assert r.status_code == 403
    assert r.get_json()["error"] == "cross-site request blocked"
    assert store.list() == []


def test_cross_site_referer_is_blocked_when_origin_absent(tmp_path, monkeypatch):
    client, store = _client(tmp_path, monkeypatch)

    r = client.post(
        "/api/alarms",
        base_url="http://deskbar.local:8080",
        headers={"Referer": "https://evil.example/page"},
        json={"time": "09:30", "days": [], "label": "偷塞"},
    )

    assert r.status_code == 403
    assert store.list() == []


def test_no_origin_usage_push_still_works(tmp_path, monkeypatch):
    state = AppState()
    client, _ = _client(tmp_path, monkeypatch, usage_state=state)

    r = client.post(
        "/api/usage",
        base_url="http://deskbar.local:8080",
        json={
            "session_pct": 12.0,
            "session_resets_at": "2026-08-11T12:00:00Z",
            "weekly_pct": 34.0,
            "weekly_resets_at": "2026-08-17T00:00:00Z",
            "fable_pct": None,
            "fable_resets_at": None,
        },
    )

    assert r.status_code == 204
    assert state.snapshot().usage.session_pct == 12.0
