"""Tests verifying facade adapter seam and webapi package integration."""

from deskbar.alarms import AlarmStore
from deskbar.webapi import create_app as webapi_create_app, start_web as webapi_start_web
from deskbar.webapi.context import WebContext
from deskbar.webserver import create_app as facade_create_app, start_web as facade_start_web


def test_facade_reexports_same_factories():
    assert facade_create_app is webapi_create_app
    assert facade_start_web is webapi_start_web


def test_create_app_returns_flask_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    store = AlarmStore()
    store.load()
    app = facade_create_app(store)
    assert app.name == "deskbar"
    client = app.test_client()
    resp = client.get("/api/alarms")
    assert resp.status_code == 200


def test_webcontext_dataclass():
    store = object()
    ctx = WebContext(store=store)
    assert ctx.store is store
    assert ctx.calendars_available is False
