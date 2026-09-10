import json
from deskbar import config


def test_defaults_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    s = config.load_settings()
    assert s.rotation == 90 and s.start_hour == 8 and s.end_hour == 24
    assert s.accounts == {}
    assert s.usage_sources == config.VALID_USAGE_SOURCES
    assert s.oa_hidden == ()
    assert s.pet_enabled is True
    assert (s.pet_x, s.pet_y) == (config.DEFAULT_PET_X, config.DEFAULT_PET_Y)


def test_usage_sources_roundtrip_empty_and_invalid_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        json.dumps({"usage_sources": []}), encoding="utf-8")
    s = config.load_settings()
    assert s.usage_sources == ()
    config.save_settings(s)
    assert config.load_settings().usage_sources == ()

    (tmp_path / "settings.json").write_text(
        json.dumps({"usage_sources": ["claude", "unknown"]}), encoding="utf-8")
    assert config.load_settings().usage_sources == config.VALID_USAGE_SOURCES


def test_oa_hidden_roundtrip_and_invalid_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        json.dumps({"oa_hidden": [" acct-a ", "acct-b", "acct-a"]}), encoding="utf-8")
    s = config.load_settings()
    assert s.oa_hidden == ("acct-a", "acct-b")
    config.save_settings(s)
    assert config.load_settings().oa_hidden == ("acct-a", "acct-b")

    for value in ("acct-a", ["acct-a", 1], [""], [str(i) for i in range(9)]):
        (tmp_path / "settings.json").write_text(
            json.dumps({"oa_hidden": value}), encoding="utf-8")
        assert config.load_settings().oa_hidden == ()


def test_normalize_oa_hidden_dedupes_preserving_order():
    assert config.normalize_oa_hidden(["b", "a", "b", " c "]) == ("b", "a", "c")


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
    assert config.DEFAULT_SCENES == ("stars", "planet_horizon", "glass_rain", "magnetic_fog", "reverse_lightning", "tidal_aurora")
    unapproved = set(config.SCENE_KEYS) - set(config.DEFAULT_SCENES)
    assert unapproved == {
        "flow", "ridges", "fireflies", "fish", "aurora", "train", "runner", "ink",
    }
    assert all(k in config.SCENE_KEYS for k in config.DEFAULT_SCENES)


def test_sisi_is_not_a_scene_and_old_sisi_scene_setting_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    assert "sisi" not in config.SCENE_KEYS
    (tmp_path / "settings.json").write_text(
        json.dumps({"scenes_enabled": ["sisi"]}), encoding="utf-8")
    s = config.load_settings()
    assert s.scenes_enabled == config.DEFAULT_SCENES


def test_pet_settings_roundtrip_and_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    s = config.load_settings()
    s.pet_enabled = False
    s.pet_x = 123
    s.pet_y = 45
    config.save_settings(s)
    loaded = config.load_settings()
    assert loaded.pet_enabled is False
    assert (loaded.pet_x, loaded.pet_y) == (123, 45)

    (tmp_path / "settings.json").write_text(
        json.dumps({"pet_enabled": "yes", "pet_x": -1, "pet_y": 900}), encoding="utf-8")
    invalid = config.load_settings()
    assert invalid.pet_enabled is True
    assert (invalid.pet_x, invalid.pet_y) == (config.DEFAULT_PET_X, config.DEFAULT_PET_Y)


def test_presence_interval_below_20_falls_back_to_45(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        json.dumps({"presence_interval_sec": 15}), encoding="utf-8")
    s = config.load_settings()
    assert s.presence_interval_sec == 45


def test_presence_source_invalid_falls_back_to_bluetooth(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        json.dumps({"presence_source": "invalid_mode"}), encoding="utf-8")
    s = config.load_settings()
    assert s.presence_source == "bluetooth"


def test_presence_push_ttl_sec_invalid_falls_back_to_900(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        json.dumps({"presence_push_ttl_sec": 30}), encoding="utf-8")  # < 60
    s = config.load_settings()
    assert s.presence_push_ttl_sec == 900

    (tmp_path / "settings.json").write_text(
        json.dumps({"presence_push_ttl_sec": "900"}), encoding="utf-8")  # 非 int
    s2 = config.load_settings()
    assert s2.presence_push_ttl_sec == 900


def test_weather_metar_station_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))

    # 預設值為 RCSS
    s = config.load_settings()
    assert s.weather_metar_station == "RCSS"

    # 允許空字串（停用）
    (tmp_path / "settings.json").write_text(
        json.dumps({"weather_metar_station": ""}), encoding="utf-8")
    s_empty = config.load_settings()
    assert s_empty.weather_metar_station == ""

    # 正常站名 roundtrip
    s_empty.weather_metar_station = "RCTP"
    config.save_settings(s_empty)
    s_rctp = config.load_settings()
    assert s_rctp.weather_metar_station == "RCTP"

    # 非字串或長度 > 8 落回 RCSS
    (tmp_path / "settings.json").write_text(
        json.dumps({"weather_metar_station": 12345}), encoding="utf-8")
    assert config.load_settings().weather_metar_station == "RCSS"

    (tmp_path / "settings.json").write_text(
        json.dumps({"weather_metar_station": "TOO_LONG_STATION_NAME"}), encoding="utf-8")
    assert config.load_settings().weather_metar_station == "RCSS"


def test_presence_source_ble_retained(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        json.dumps({"presence_source": "ble"}), encoding="utf-8")
    s = config.load_settings()
    assert s.presence_source == "ble"


def test_center_view_allows_sessions_and_invalid_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        json.dumps({"center_view": "sessions"}), encoding="utf-8")
    s = config.load_settings()
    assert s.center_view == "sessions"
    config.save_settings(s)
    assert config.load_settings().center_view == "sessions"

    (tmp_path / "settings.json").write_text(
        json.dumps({"center_view": "invalid_view"}), encoding="utf-8")
    assert config.load_settings().center_view == "calendar"
