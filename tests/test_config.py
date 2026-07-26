import json
from deskbar import config


def test_defaults_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    s = config.load_settings()
    assert s.rotation == 90 and s.start_hour == 8 and s.end_hour == 24
    assert s.accounts == {}


def test_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    s = config.load_settings()
    acc = s.ensure_account("a@example.com")
    acc.lane_label = "工作"
    acc.calendars["a@example.com"] = True
    s.rotation = 270
    config.save_settings(s)
    s2 = config.load_settings()
    assert s2.rotation == 270
    assert s2.accounts["a@example.com"].lane_label == "工作"
    assert s2.accounts["a@example.com"].calendars == {"a@example.com": True}


def test_ensure_account_assigns_distinct_colors(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    s = config.load_settings()
    c0 = s.ensure_account("a@x.com").color
    c1 = s.ensure_account("b@x.com").color
    assert c0 != c1
    assert s.ensure_account("a@x.com").color == c0  # 冪等


def test_corrupt_file_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text("{broken", encoding="utf-8")
    s = config.load_settings()
    assert s.rotation == 90
