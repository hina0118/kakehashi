import json

import pytest
from fastapi.testclient import TestClient

from kakehashi.api.app import create_app
from kakehashi.config import config_path
from kakehashi.infra.deck import DeckNotConfiguredError


@pytest.fixture
def client(ctx):
    return TestClient(create_app(ctx), base_url="http://127.0.0.1", headers={"X-Kakehashi": "1"})


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


def test_mutations_require_csrf_header(ctx):
    plain = TestClient(create_app(ctx), base_url="http://127.0.0.1")
    res = plain.post("/api/esde/ps2/media/sync", json={"direction": "pull"})
    assert res.status_code == 403
    assert plain.get("/api/esde/systems").status_code == 200


def test_rejects_non_local_host(ctx):
    evil = TestClient(create_app(ctx), base_url="http://evil.example", headers={"X-Kakehashi": "1"})
    assert evil.get("/api/esde/systems").status_code == 403


def test_media_job_runs_in_background(client, ctx):
    import time

    from pathlib import Path
    cover = Path(ctx.config.windows.media_base) / "ps2" / "covers" / "a.png"
    cover.parent.mkdir(parents=True)
    cover.write_text("x")

    job = client.post("/api/esde/ps2/media/sync", json={"direction": "push"}).json()
    for _ in range(100):
        view = client.get(f"/api/jobs/{job['id']}").json()
        if view["status"] != "running":
            break
        time.sleep(0.02)
    assert view["status"] == "done", view
    assert view["result"]["transferred"] == 1


def test_media_file_404_and_thumbnail(client, ctx):
    from pathlib import Path

    from PIL import Image
    assert client.get("/api/esde/ps2/media/file/covers/none.png").status_code == 404
    p = Path(ctx.config.windows.media_base) / "ps2" / "covers" / "a.png"
    p.parent.mkdir(parents=True)
    Image.new("RGB", (400, 300)).save(p)
    res = client.get("/api/esde/ps2/media/file/covers/a.png", params={"w": 100})
    assert res.headers["content-type"] == "image/png"
    assert client.get("/api/esde/ps2/media", params={"path": "./a.chd"}).json()["files"]["covers"]["filename"] == "a.png"
