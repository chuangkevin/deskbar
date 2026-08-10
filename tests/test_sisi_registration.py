"""喜喜桌面寵物的公開設定入口。"""
from __future__ import annotations

import threading

from deskbar.config import DEFAULT_SCENES, SCENE_KEYS, Settings
from deskbar.ui import scenes
from deskbar.ui.sisi_pet import SisiPet
from deskbar.webserver import create_app


class _FakeStore:
    def list(self):
        return []


def _client():
    settings = Settings()
    saved = []
    app = create_app(_FakeStore(), settings_provider=settings,
                     settings_lock=threading.Lock(), on_save=lambda _: saved.append(True))
    app.config["TESTING"] = True
    return app.test_client(), settings, saved


def test_sisi_is_pet_not_scene():
    assert "sisi" not in SCENE_KEYS
    assert "sisi" not in DEFAULT_SCENES
    assert "sisi" not in scenes._FACTORIES
    pet = SisiPet(Settings())
    assert pet.position() == (Settings().pet_x, Settings().pet_y)
    pet.close()


def test_phone_settings_exposes_sisi_pet_toggle_and_persists_it():
    client, settings, saved = _client()
    html = client.get("/").get_data(as_text=True)
    assert "小喜喜桌面寵物" in html
    assert '["sisi","喜喜"]' not in html

    response = client.patch("/api/prefs", json={"pet_enabled": False})

    assert response.status_code == 200
    assert settings.pet_enabled is False
    assert saved
