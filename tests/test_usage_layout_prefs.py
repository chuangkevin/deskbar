"""右欄排版設定（2026-09-23 第 1 段）：usage_order / usage_width / usage_density。

- apply_order：section 排序純函數
- prefs GET/POST：三欄位讀寫＋範圍外 400
- apply_usage_width：版面常數重算（rebind；函式內 import 讀到新值）＋還原
- CC 前綴：CommandCode 卡片標題為 CC · <名>（別名照舊）
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pygame
import pytest

from deskbar import config
from deskbar.alarms import AlarmStore
from deskbar.claudeusage import CcAccount, OaAccount, UsageInfo
from deskbar.config import Settings
from deskbar.store import AppState
from deskbar.ui import dashboard, theme, usagewidget
from deskbar.webserver import create_app

TZ = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 9, 23, 16, 0, tzinfo=TZ)


def _sections():
    return [
        ("CLAUDE CODE", [("5H SESSION", 1.0, None, 18000)], 0.0, "claude"),
        ("ANTIGRAVITY · GEMINI", [("5H", 2.0, None, 18000)], 0.0, "antigravity"),
        ("CC · KS", [("5H", 3.0, None, 18000)], 0.0, "commandcode:cc1"),
        ("OPENCODE GO", [("5H", 4.0, None, 18000)], 0.0, "opencode:og1"),
    ]


# ---------------------------------------------------------------- apply_order


def test_apply_order_puts_listed_keys_first_in_listed_sequence():
    out = usagewidget.apply_order(_sections(), ["opencode:og1", "claude"])
    assert [k for _t, _g, _a, k in out] == [
        "opencode:og1", "claude", "antigravity", "commandcode:cc1"]


def test_apply_order_ignores_unknown_keys():
    out = usagewidget.apply_order(_sections(), ["nope:1", "claude", "nope:2"])
    assert [k for _t, _g, _a, k in out] == [
        "claude", "antigravity", "commandcode:cc1", "opencode:og1"]


def test_apply_order_empty_or_none_keeps_original():
    assert usagewidget.apply_order(_sections(), []) == _sections()
    assert usagewidget.apply_order(_sections(), None) == _sections()
    assert usagewidget.apply_order(_sections(), ()) == _sections()


def test_apply_order_full_reverse():
    out = usagewidget.apply_order(
        _sections(), ["opencode:og1", "commandcode:cc1", "antigravity", "claude"])
    assert [k for _t, _g, _a, k in out] == [
        "opencode:og1", "commandcode:cc1", "antigravity", "claude"]


def test_apply_order_does_not_mutate_input():
    sections = _sections()
    snapshot = list(sections)
    usagewidget.apply_order(sections, ["opencode:og1"])
    assert sections == snapshot


def test_render_respects_order_opencode_first():
    """render(order=[opencode...])：opencode 卡片畫在最左欄第一張。"""
    from deskbar.claudeusage import OgAccount
    from dataclasses import replace
    usage = UsageInfo(
        session_pct=7.0, session_resets_at=NOW + timedelta(hours=4),
        weekly_pct=37.0, weekly_resets_at=NOW + timedelta(days=5),
        fable_pct=None, fable_resets_at=None, fetched_at=NOW,
        og_accounts=(OgAccount("og1", "", 0.0, NOW + timedelta(hours=5),
                               75.0, NOW + timedelta(days=5),
                               100.0, NOW + timedelta(days=18),
                               NOW + timedelta(days=18), NOW),),
        og_fetched_at=NOW)
    surf = pygame.Surface((1920, 480))
    surf.fill(theme.C["bg"])
    res = usagewidget.render(surf, usage, NOW, 1300, 600,
                             ("claude", "opencode"),
                             order=["opencode:og1", "claude"])
    assert res["keys"][0] == "opencode:og1"


# ---------------------------------------------------------------- CC 前綴


def _cc_account(aid="cc1", name="ks"):
    return CcAccount(aid, name, 20.0, NOW + timedelta(hours=3),
                     40.0, NOW + timedelta(days=3),
                     NOW + timedelta(days=20), NOW)


def _usage_with_cc(accounts):
    return UsageInfo(
        session_pct=1.0, session_resets_at=NOW + timedelta(hours=1),
        weekly_pct=1.0, weekly_resets_at=NOW + timedelta(days=1),
        fable_pct=None, fable_resets_at=None, fetched_at=NOW,
        cc_accounts=tuple(accounts), cc_fetched_at=NOW)


def test_cc_title_uses_cc_prefix_without_alias():
    sections = usagewidget.visible_sections(
        _usage_with_cc([_cc_account()]), NOW, ("commandcode",))
    assert [t for t, _g, _a, _k in sections] == ["CC · KS"]


def test_cc_title_uses_alias_after_prefix():
    sections = usagewidget.visible_sections(
        _usage_with_cc([_cc_account(aid="cc1", name="kevin202511180ysi")]), NOW,
        ("commandcode",), cc_aliases={"cc1": "ks"})
    assert [t for t, _g, _a, _k in sections] == ["CC · ks"]


def test_cc_legacy_single_section_title_is_cc():
    from dataclasses import replace
    usage = replace(_usage_with_cc([]), cc_5h_pct=6.0,
                    cc_5h_resets_at=NOW + timedelta(hours=3),
                    cc_weekly_pct=72.0,
                    cc_weekly_resets_at=NOW + timedelta(days=3))
    sections = usagewidget.visible_sections(usage, NOW, ("commandcode",))
    assert [t for t, _g, _a, _k in sections] == ["CC"]


# ---------------------------------------------------------------- prefs GET/POST


def _prefs_client(tmp_path, monkeypatch):
    import threading
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    settings = Settings()
    saved = []
    app = create_app(AlarmStore(), settings_provider=settings,
                     settings_lock=threading.Lock(), on_save=lambda s: saved.append(1))
    app.config["TESTING"] = True
    client = app.test_client()
    client._settings = settings
    return client, settings


def test_prefs_get_returns_new_fields_with_defaults():
    import tempfile, os
    tmp = tempfile.mkdtemp()
    import threading
    settings = Settings()
    app = create_app(AlarmStore(), settings_provider=settings,
                     settings_lock=threading.Lock(), on_save=lambda s: None)
    app.config["TESTING"] = True
    client = app.test_client()
    d = client.get("/api/prefs").get_json()
    assert d["usage_order"] == []
    assert d["usage_width"] == 600
    assert d["usage_density"] == "auto"


def test_prefs_post_roundtrips_new_fields(tmp_path, monkeypatch):
    client, settings = _prefs_client(tmp_path, monkeypatch)
    r = client.patch("/api/prefs", json={
        "usage_order": ["opencode:abc123", "claude"],
        "usage_width": 800,
        "usage_density": "compact",
    })
    assert r.status_code == 200
    assert settings.usage_order == ("opencode:abc123", "claude")
    assert settings.usage_width == 800
    assert settings.usage_density == "compact"
    d = client.get("/api/prefs").get_json()
    assert d["usage_order"] == ["opencode:abc123", "claude"]
    assert d["usage_width"] == 800
    assert d["usage_density"] == "compact"


@pytest.mark.parametrize("payload", [
    {"usage_order": "claude"},
    {"usage_order": ["ok"] * 65},
    {"usage_order": [""]},
    {"usage_order": ["x" * 81]},
    {"usage_order": [123]},
    {"usage_order": [True]},
    {"usage_width": 359},
    {"usage_width": 1101},
    {"usage_width": "800"},
    {"usage_width": True},
    {"usage_width": 800.0},
    {"usage_density": "dense"},
    {"usage_density": ""},
    {"usage_density": None},
    {"usage_density": 123},
])
def test_prefs_post_rejects_out_of_range(tmp_path, monkeypatch, payload):
    client, settings = _prefs_client(tmp_path, monkeypatch)
    before = (settings.usage_order, settings.usage_width, settings.usage_density)
    assert client.patch("/api/prefs", json=payload).status_code == 400
    assert (settings.usage_order, settings.usage_width, settings.usage_density) == before


@pytest.mark.parametrize("payload,expected", [
    ({"usage_width": 360}, 360),
    ({"usage_width": 1100}, 1100),
    ({"usage_density": "normal"}, "normal"),
    ({"usage_order": []}, ()),
])
def test_prefs_post_accepts_boundaries(tmp_path, monkeypatch, payload, expected):
    client, settings = _prefs_client(tmp_path, monkeypatch)
    assert client.patch("/api/prefs", json=payload).status_code == 200
    key = next(iter(payload))
    assert getattr(settings, key) == expected


# ---------------------------------------------------------------- config normalize


def test_normalize_usage_order_trims_dedups_rejects():
    assert config.normalize_usage_order([" b ", "a", "b"]) == ("b", "a")
    assert config.normalize_usage_order(["x" * 80]) == ("x" * 80,)
    assert config.normalize_usage_order("claude") == ()
    assert config.normalize_usage_order(["a"] * 65) == ()
    assert config.normalize_usage_order([""]) == ()
    assert config.normalize_usage_order(["x" * 81]) == ()
    assert config.normalize_usage_order([123]) == ()
    assert config.normalize_usage_order(None) == ()


def test_normalize_usage_width_and_density():
    assert config.normalize_usage_width(800) == 800
    assert config.normalize_usage_width(359) == 600
    assert config.normalize_usage_width(1101) == 600
    assert config.normalize_usage_width("800") == 600
    assert config.normalize_usage_width(True) == 600
    assert config.normalize_usage_density("compact") == "compact"
    assert config.normalize_usage_density("dense") == "auto"
    assert config.normalize_usage_density(None) == "auto"


def test_settings_roundtrip_new_fields(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    s = Settings(usage_order=("opencode:abc", "claude"), usage_width=800,
                 usage_density="compact")
    config.save_settings(s)
    raw = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert raw["usage_order"] == ["opencode:abc", "claude"]
    assert raw["usage_width"] == 800
    assert raw["usage_density"] == "compact"
    loaded = config.load_settings()
    assert loaded.usage_order == ("opencode:abc", "claude")
    assert loaded.usage_width == 800
    assert loaded.usage_density == "compact"


# ---------------------------------------------------------------- apply_usage_width


@pytest.fixture
def restore_layout():
    yield
    dashboard.apply_usage_width(config.DEFAULT_USAGE_WIDTH)


def test_apply_usage_width_800_recomputes_all(restore_layout):
    dashboard.apply_usage_width(800)
    assert dashboard.TL_X1 == 1080
    assert dashboard.USAGE_X0 == 1100
    assert dashboard.USAGE_W == 800
    assert (dashboard.TL_AREA.x, dashboard.TL_AREA.y,
            dashboard.TL_AREA.w, dashboard.TL_AREA.h) == (420, 52, 660, 368)
    from deskbar.ui.dashboard import CENTER_SLIDE_AREA
    assert (CENTER_SLIDE_AREA.x, CENTER_SLIDE_AREA.y,
            CENTER_SLIDE_AREA.w, CENTER_SLIDE_AREA.h) == (402, 52, 678, 428)
    from deskbar.ui.dashboard import MODE_BTN, SPAN_BTN, CENTER_BTN, WORK_BTN
    assert (MODE_BTN.x, MODE_BTN.y, MODE_BTN.w, MODE_BTN.h) == (968, 2, 110, 48)
    assert (SPAN_BTN.x, SPAN_BTN.y, SPAN_BTN.w, SPAN_BTN.h) == (850, 2, 110, 48)
    assert (CENTER_BTN.x, CENTER_BTN.y, CENTER_BTN.w, CENTER_BTN.h) == (732, 2, 110, 48)
    assert (WORK_BTN.x, WORK_BTN.y, WORK_BTN.w, WORK_BTN.h) == (594, 2, 130, 48)


def test_apply_usage_width_restores_defaults(restore_layout):
    dashboard.apply_usage_width(800)
    dashboard.apply_usage_width(600)
    assert dashboard.TL_X1 == dashboard._DEFAULT_TL_X1 == 1280
    assert dashboard.USAGE_X0 == dashboard._DEFAULT_USAGE_X0 == 1300
    assert dashboard.USAGE_W == dashboard._DEFAULT_USAGE_W == 600
    from deskbar.ui.dashboard import CENTER_SLIDE_AREA
    assert (CENTER_SLIDE_AREA.x, CENTER_SLIDE_AREA.y,
            CENTER_SLIDE_AREA.w, CENTER_SLIDE_AREA.h) == (
        dashboard._DEFAULT_CENTER_SLIDE_AREA.x,
        dashboard._DEFAULT_CENTER_SLIDE_AREA.y,
        dashboard._DEFAULT_CENTER_SLIDE_AREA.w,
        dashboard._DEFAULT_CENTER_SLIDE_AREA.h)
    from deskbar.ui.dashboard import MODE_BTN, SPAN_BTN, CENTER_BTN, WORK_BTN
    assert (MODE_BTN.x, MODE_BTN.y, MODE_BTN.w, MODE_BTN.h) == (
        dashboard._DEFAULT_MODE_BTN.x, dashboard._DEFAULT_MODE_BTN.y,
        dashboard._DEFAULT_MODE_BTN.w, dashboard._DEFAULT_MODE_BTN.h)
    assert (WORK_BTN.x, WORK_BTN.y, WORK_BTN.w, WORK_BTN.h) == (
        dashboard._DEFAULT_WORK_BTN.x, dashboard._DEFAULT_WORK_BTN.y,
        dashboard._DEFAULT_WORK_BTN.w, dashboard._DEFAULT_WORK_BTN.h)
    assert dashboard.TL_AREA == dashboard._DEFAULT_TL_AREA
    # 頂帶四顆鈕仍在中欄內且互不重疊
    btns = sorted([WORK_BTN, CENTER_BTN, SPAN_BTN, MODE_BTN], key=lambda r: r.x)
    for r in btns:
        assert r.x >= dashboard.TL_X0 and r.x + r.w <= dashboard.TL_X1
    for a, b in zip(btns, btns[1:]):
        assert a.x + a.w <= b.x


def test_apply_usage_width_clamps_out_of_range(restore_layout):
    dashboard.apply_usage_width(200)
    assert dashboard.USAGE_W == 600
    dashboard.apply_usage_width(2000)
    assert dashboard.USAGE_W == 600


def test_min_columns_for_width():
    assert usagewidget.min_columns_for_width(600) == 2
    assert usagewidget.min_columns_for_width(800) == 2
    assert usagewidget.min_columns_for_width(900) == 3
    assert usagewidget.min_columns_for_width(360) == 1


def test_density_normal_never_compacts_and_compact_always_compacts():
    counts = [3, 2, 2]
    normal = usagewidget.fit_layout(counts, density="normal")
    assert normal["compact"] is False
    assert normal["group_step"] == usagewidget.GROUP_STEP
    compact = usagewidget.fit_layout(counts, density="compact")
    assert compact["compact"] is True
    tight = usagewidget._scaled(0.0)
    assert compact["group_step"] == tight["group_step"]
    assert compact["first_group"] == tight["first_group"]


def test_fixed_density_reports_overflow_so_render_adds_a_column():
    """2026-09-23 實機：寬度 800＋緊湊，左欄 5 張卡片要 491px > 474px，
    以前 compact 一律回報放得下，最後一張卡片被畫到螢幕外。"""
    from deskbar.ui import usagewidget as u
    counts = [3, 3, 2, 1, 1]
    for density in ("compact", "normal"):
        layout = u.fit_layout(counts, u.DEFAULT_HEIGHT, density=density)
        assert layout["max_sections"] < len(counts), density
    assert u.fit_layout([3, 1], u.DEFAULT_HEIGHT, density="compact")["max_sections"] == 2
