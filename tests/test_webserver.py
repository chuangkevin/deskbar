import pytest
from deskbar.alarms import AlarmStore
from deskbar.webserver import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKBAR_CONFIG_DIR", str(tmp_path))
    store = AlarmStore()
    store.load()
    return create_app(store).test_client()


def test_crud_flow(client):
    r = client.post("/api/alarms", json={"time": "09:00", "days": [0, 1], "label": "打卡",
                                           "arrival_trigger": True})
    assert r.status_code == 201
    aid = r.get_json()["id"]
    r = client.get("/api/alarms")
    assert [a["label"] for a in r.get_json()] == ["打卡"]
    assert r.get_json()[0]["arrival_trigger"] is True
    r = client.patch(f"/api/alarms/{aid}", json={"enabled": False})
    assert r.status_code == 200
    assert client.get("/api/alarms").get_json()[0]["enabled"] is False
    assert client.patch(f"/api/alarms/{aid}", json={"arrival_trigger": False}).status_code == 200
    assert client.get("/api/alarms").get_json()[0]["arrival_trigger"] is False
    assert client.delete(f"/api/alarms/{aid}").status_code == 204
    assert client.get("/api/alarms").get_json() == []


def test_validation(client):
    assert client.post("/api/alarms", json={"time": "25:00", "days": [], "label": "x"}).status_code == 400
    assert client.post("/api/alarms", json={"time": "09:00", "days": [7], "label": "x"}).status_code == 400
    assert client.patch("/api/alarms/nope", json={"enabled": True}).status_code == 404
    assert client.delete("/api/alarms/nope").status_code == 404
    assert client.post("/api/alarms", json={"time": 900, "days": [0], "label": "x"}).status_code == 400
    assert client.post("/api/alarms", json={"time": None, "days": [0], "label": "x"}).status_code == 400
    assert client.post("/api/alarms", json={"time": "09:00", "days": [], "label": "x",
                                             "arrival_trigger": "yes"}).status_code == 400
    assert client.post("/api/alarms", json={"time": "09:00", "days": [True], "label": "x"}).status_code == 400
    assert client.patch("/api/alarms/nope", json={}).status_code == 400


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "deskbar" in r.get_data(as_text=True)


def test_patch_alarm_skip_date_api(client):
    r = client.post("/api/alarms", json={"time": "09:00", "days": [0, 1], "label": "打卡"})
    aid = r.get_json()["id"]

    assert client.patch(f"/api/alarms/{aid}", json={"enabled": True}).status_code == 200

    r = client.patch(f"/api/alarms/{aid}", json={"skip_date": "2026-08-06"})
    assert r.status_code == 200
    assert client.get("/api/alarms").get_json()[0]["skip_date"] == "2026-08-06"

    r = client.patch(f"/api/alarms/{aid}", json={"skip_date": None})
    assert r.status_code == 200
    assert client.get("/api/alarms").get_json()[0]["skip_date"] is None

    assert client.patch(f"/api/alarms/{aid}", json={}).status_code == 400
    assert client.patch(f"/api/alarms/{aid}", json={"skip_date": "亂寫"}).status_code == 400
    assert client.patch(f"/api/alarms/{aid}", json={"enabled": "yes"}).status_code == 400
    assert client.patch(f"/api/alarms/{aid}", json={"arrival_trigger": "yes"}).status_code == 400
    assert client.patch("/api/alarms/nope", json={"skip_date": "2026-08-06"}).status_code == 404


def test_patch_alarm_edits_time_days_label_and_arrival(client):
    aid = client.post("/api/alarms", json={"time": "09:00", "days": [0], "label": "提醒"}).get_json()["id"]
    r = client.patch(f"/api/alarms/{aid}", json={
        "time": "08:45", "days": [4, 1, 1], "label": "打卡", "arrival_trigger": True,
    })
    assert r.status_code == 200
    got = r.get_json()
    assert (got["time"], got["days"], got["label"], got["arrival_trigger"]) == (
        "08:45", [1, 4], "打卡", True)
    assert client.patch(f"/api/alarms/{aid}", json={"time": "bad"}).status_code == 400
