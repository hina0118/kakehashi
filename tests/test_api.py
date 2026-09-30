import json

import pytest
from fastapi.testclient import TestClient

from kakehashi.api.app import create_app
from kakehashi.config import config_path
from kakehashi.infra.deck import DeckNotConfiguredError


@pytest.fixture
def client(ctx):
    return TestClient(create_app(ctx))


def test_list_games_with_unregistered(client):
    res = client.get("/api/esde/ps2/games", params={"include_unregistered": True})
    assert res.status_code == 200
    assert [(g["path"], g["registered"]) for g in res.json()] == [
        ("./a.chd", True), ("./b.chd", True), ("./c.chd", False),
    ]


def test_update_games(client):
    res = client.post("/api/esde/ps2/games/update", json={
        "updates": [{"path": "./a.chd", "fields": {"name": "A!"}}],
        "deleted": ["./b.chd"],
    })
    assert res.json() == {"applied": 1, "deleted": 1, "requested": 2}
    assert [g["name"] for g in client.get("/api/esde/ps2/games").json()] == ["A!"]


def test_update_invalid_field_is_422(client):
    res = client.post("/api/esde/ps2/games/update", json={
        "updates": [{"path": "./a.chd", "fields": {"favorite": "x"}}],
    })
    assert res.status_code == 422


def test_deck_not_configured_is_400(client, ctx):
    def _raise():
        raise DeckNotConfiguredError("未設定")
    ctx.connect = _raise
    res = client.get("/api/esde/ps2/games")
    assert (res.status_code, res.json()["code"]) == (400, "deck_not_configured")


def test_settings_hide_password_and_keep_it_when_omitted(client):
    view = client.get("/api/settings").json()
    assert view["sync"] == {"host": "deck.test", "port": 22, "username": "deck", "password_set": True}

    body = {**view, "sync": {"host": "10.0.0.2", "port": 22, "username": "deck"}}
    del body["sync"]  # password_set は入力に含めない
    body["sync"] = {"host": "10.0.0.2", "port": 22, "username": "deck"}
    assert client.put("/api/settings", json=body).status_code == 200

    saved = json.loads(config_path().read_text(encoding="utf-8"))
    assert saved["sync"]["host"] == "10.0.0.2"
    assert saved["sync"]["password"] == "secret"
