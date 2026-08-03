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


def test_theme_defaults_to_dark(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    s = config.load_settings()
    assert s.theme == "dark"


def test_theme_roundtrips_through_save(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    s = config.load_settings()
    s.theme = "light"
    config.save_settings(s)
    s2 = config.load_settings()
    assert s2.theme == "light"


def test_invalid_theme_value_falls_back_to_dark(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        json.dumps({"theme": "solarized-purple-neon"}), encoding="utf-8")
    s = config.load_settings()
    assert s.theme == "dark"


def test_non_string_theme_value_falls_back_to_dark(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(json.dumps({"theme": 42}), encoding="utf-8")
    s = config.load_settings()
    assert s.theme == "dark"


def test_approved_planet_horizon_is_in_default_scene_rotation():
    assert "planet_horizon" in config.SCENE_KEYS
    assert "planet_horizon" in config.DEFAULT_SCENES
    assert config.Settings().scenes_enabled == config.DEFAULT_SCENES


def test_default_rotation_only_contains_visually_approved_scenes():
    # DESIGN.md §100：晨／晝／夜驗證圖經人工核可後才准入預設輪播。
    # 未核可的場景仍可在網頁手動勾選，只是不預設出現——這條測試把那道閘門釘住，
    # 免得日後新增場景時又順手塞回 SCENE_KEYS 全集。
    assert config.DEFAULT_SCENES == ("flow", "stars", "ridges", "aurora", "planet_horizon")
    unapproved = set(config.SCENE_KEYS) - set(config.DEFAULT_SCENES)
    assert unapproved == {"fireflies", "fish", "train", "runner", "ink"}
    assert all(k in config.SCENE_KEYS for k in config.DEFAULT_SCENES)
