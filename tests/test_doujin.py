import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from kakehashi.api.app import create_app
from kakehashi.config import DeckPaths
from kakehashi.domain.doujin import DoujinPatch, guess_from_folder_name, rank_exe_candidates
from kakehashi.errors import NotFoundError
from kakehashi.infra import dlsite
from kakehashi.infra.doujin_db import DoujinDB
from kakehashi.services.jobs import Job


@pytest.fixture
def ctx_doujin(ctx):
    ctx.config.steam_deck = DeckPaths(
        **{**ctx.config.steam_deck.model_dump(), "doujin_base": ["/deck/doujin", "/deck/sd/doujin"]}
    )
    return ctx


def make_game(root: Path, name: str, files: dict[str, str] | None = None) -> Path:
    d = root / name
    for rel, text in (files or {"Game.exe": "exe", "www/data.json": "{}"}).items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(text, encoding="utf-8")
    return d


@pytest.mark.parametrize("name, expected", [
    ("[サークルA] 勇者の冒険 RJ01234567", ("勇者の冒険", "サークルA", "RJ01234567", "dlsite")),
    ("rj123456_魔法少女", ("魔法少女", "", "RJ123456", "dlsite")),
    ("【Circle】Title (d_234567)", ("Title", "Circle", "d_234567", "fanza")),
    ("ただのフォルダ", ("ただのフォルダ", "", "", "")),
])
def test_guess_from_folder_name(name, expected):
    g = guess_from_folder_name(name)
    assert (g.title, g.circle, g.work_id, g.store) == expected


def test_rank_exe_candidates_skips_helpers():
    files = [
        "unins000.exe", "UnityCrashHandler64.exe", "nw.exe", "Game.exe",
        "tools/Config.exe", "bin/Launcher.exe", "readme.txt",
    ]
    assert rank_exe_candidates(files) == ["Game.exe", "nw.exe", "bin/Launcher.exe"]


def test_register_folder_guesses_and_rejects_duplicates(ctx_doujin, tmp_path):
    folder = make_game(tmp_path / "games", "[CircleX] 冒険 RJ01234567", {
        "unins000.exe": "", "Game.exe": "", "www/img.png": "",
    })
    g = ctx_doujin.doujin.register_folder(str(folder))
    assert (g.title, g.circle, g.work_id, g.exe) == ("冒険", "CircleX", "RJ01234567", "Game.exe")
    assert g.url.endswith("RJ01234567.html")
    with pytest.raises(ValueError):
        ctx_doujin.doujin.register_folder(str(folder))


def test_scan_parent_and_register_many(ctx_doujin, tmp_path):
    root = tmp_path / "games"
    a = make_game(root, "A RJ111111")
    make_game(root, "B")
    ctx_doujin.doujin.register_folder(str(a))

    cands = ctx_doujin.doujin.scan_parent(str(root))
    assert [(c.name, c.registered_id is not None) for c in cands] == [("A RJ111111", True), ("B", False)]

    created = ctx_doujin.doujin.register_many([c.path for c in cands])
    assert [g.title for g in created] == ["B"]
    assert len(ctx_doujin.doujin.list()) == 2


def test_update_normalizes_tags_exe_and_rating(ctx_doujin, tmp_path):
    g = ctx_doujin.doujin.register_folder(str(make_game(tmp_path, "X")))
    g = ctx_doujin.doujin.update(g.id, DoujinPatch(tags=[" RPG", "RPG", "", "ホラー"], exe="bin\\run.exe", rating=4))
    assert (g.tags, g.exe, g.rating) == (["RPG", "ホラー"], "bin/run.exe", 4)
    g = ctx_doujin.doujin.update(g.id, DoujinPatch.model_validate({"rating": None}))
    assert g.rating is None
    assert g.tags == ["RPG", "ホラー"]  # 指定しなかった項目は変わらない


def test_images_replace_and_delete(ctx_doujin, tmp_path):
    g = ctx_doujin.doujin.register_folder(str(make_game(tmp_path, "X")))
    jpg, png = tmp_path / "c.jpg", tmp_path / "c.png"
    Image.new("RGB", (60, 90)).save(jpg)
    Image.new("RGB", (60, 90)).save(png)

    ctx_doujin.doujin.import_image_file(g.id, "cover", jpg)
    g = ctx_doujin.doujin.import_image_file(g.id, "cover", png)
    assert g.images["cover"].filename == "cover.png"
    assert not ctx_doujin.doujin.image_path(g.id, "cover").with_suffix(".jpg").exists()

    g = ctx_doujin.doujin.delete_image(g.id, "cover")
    assert g.images == {}
    with pytest.raises(ValueError):
        ctx_doujin.doujin.import_image_file(g.id, "banner", png)
    with pytest.raises(ValueError):
        ctx_doujin.doujin.import_image_file(g.id, "cover", make_game(tmp_path, "Y") / "Game.exe")


def test_delete_removes_entry_and_images(ctx_doujin, tmp_path):
    g = ctx_doujin.doujin.register_folder(str(make_game(tmp_path, "X")))
    png = tmp_path / "c.png"
    Image.new("RGB", (10, 10)).save(png)
    ctx_doujin.doujin.import_image_file(g.id, "icon", png)
    ctx_doujin.doujin.delete(g.id)
    with pytest.raises(NotFoundError):
        ctx_doujin.doujin.get(g.id)
    assert (tmp_path / "X" / "Game.exe").exists()  # 本体には触れない


def test_transfer_uses_chosen_base_then_sends_only_changes(ctx_doujin, deck_fs, tmp_path):
    folder = make_game(tmp_path, "My Game")
    g = ctx_doujin.doujin.register_folder(str(folder))

    with pytest.raises(ValueError):
        ctx_doujin.doujin.transfer(g.id, Job("t", "t"))  # 格納先の指定が必要

    res = ctx_doujin.doujin.transfer(g.id, Job("t", "t"), base="/deck/sd/doujin")
    assert res["deck_dir"] == "/deck/sd/doujin/My Game"
    assert deck_fs.files["/deck/sd/doujin/My Game/www/data.json"] == "{}"
    g = ctx_doujin.doujin.get(g.id)
    assert g.deck_dir == "/deck/sd/doujin/My Game" and g.transferred_at is not None

    (folder / "save.dat").write_text("new")
    res = ctx_doujin.doujin.transfer(g.id, Job("t", "t"), base="/deck/doujin")  # 2回目は前回の場所へ
    assert (res["deck_dir"], res["transferred"], res["skipped"]) == ("/deck/sd/doujin/My Game", 1, 2)


def test_scan_and_import_from_deck(ctx_doujin, deck_fs, tmp_path):
    deck_fs.files.update({
        "/deck/doujin/[Circ] Old Game RJ222222/Game.exe": "",
        "/deck/doujin/[Circ] Old Game RJ222222/unins000.exe": "",
        "/deck/sd/doujin/Linked/Game.exe": "",
    })
    g = ctx_doujin.doujin.register_folder(str(make_game(tmp_path, "Linked")))
    ctx_doujin.doujin.update(g.id, DoujinPatch(deck_dir="/deck/sd/doujin/Linked"))

    folders = ctx_doujin.doujin.scan_deck()
    assert [(f.name, f.linked_id is not None) for f in folders] == [
        ("[Circ] Old Game RJ222222", False), ("Linked", True),
    ]

    created = ctx_doujin.doujin.import_from_deck([f.path for f in folders])
    assert [(c.title, c.circle, c.work_id, c.exe, c.local_path) for c in created] == [
        ("Old Game", "Circ", "RJ222222", "Game.exe", ""),
    ]
    assert ctx_doujin.doujin.exe_candidates(created[0].id) == ["Game.exe"]
    with pytest.raises(ValueError):
        ctx_doujin.doujin.import_from_deck(["/etc/passwd-dir"])


def test_db_persists_across_reopen(tmp_path):
    db = DoujinDB(tmp_path / "d.db")
    row = db.create({"title": "T", "tags": ["a"]})
    db.close()
    db = DoujinDB(tmp_path / "d.db")
    assert db.get(row["id"])["tags"] == ["a"]


def test_dlsite_fetch_parses_api_and_page(monkeypatch):
    api = {"RJ01234567": {
        "work_name": "作品 &amp; 名", "site_id": "maniax", "work_type": "RPG",
        "work_image": "//img.dlsite.jp/x/RJ01234567_img_main.jpg", "regist_date": "2024-05-01 00:00:00",
    }}
    page = """<span itemprop="brand" class="maker_name"> <a href="#">サークル&amp;B</a> </span>
    <div class="main_genre"> <a href="#">ファンタジー</a> <a href="#">RPG</a> </div>"""

    def fake_get(url, timeout=20):
        return json.dumps(api) if "ajax" in url else page

    monkeypatch.setattr(dlsite, "_get", fake_get)
    info = dlsite.fetch("rj01234567")
    assert (info.work_id, info.circle, info.release_date, info.genres) == (
        "RJ01234567", "サークル&B", "2024-05-01", ["ファンタジー", "RPG"],
    )
    assert info.image_url.startswith("https://img.dlsite.jp/")
    assert info.url == "https://www.dlsite.com/maniax/work/=/product_id/RJ01234567.html"

    monkeypatch.setattr(dlsite, "_get", lambda url, timeout=20: "[]")
    with pytest.raises(NotFoundError):
        dlsite.fetch("RJ00000001")
    with pytest.raises(ValueError):
        dlsite.fetch("d_123456")


def test_api_crud(ctx_doujin, tmp_path):
    client = TestClient(create_app(ctx_doujin), base_url="http://127.0.0.1", headers={"X-Kakehashi": "1"})
    folder = make_game(tmp_path, "API Game")
    g = client.post("/api/doujin/games", json={"path": str(folder)}).json()
    res = client.patch(f"/api/doujin/games/{g['id']}", json={"play_status": "cleared", "rating": 5})
    assert (res.json()["play_status"], res.json()["rating"]) == ("cleared", 5)
    assert client.patch(f"/api/doujin/games/{g['id']}", json={"play_status": "???"}).status_code == 422
    assert client.get(f"/api/doujin/games/{g['id']}/exe-candidates").json() == ["Game.exe"]
    assert client.get(f"/api/doujin/games/{g['id']}/images/cover").status_code == 404
    assert client.delete(f"/api/doujin/games/{g['id']}").status_code == 200
    assert client.get(f"/api/doujin/games/{g['id']}").status_code == 404


def test_import_from_deck_links_existing_entry_instead_of_duplicating(ctx_doujin, deck_fs, tmp_path):
    by_id = ctx_doujin.doujin.register_folder(str(make_game(tmp_path, "renamed locally RJ333333")))
    by_name = ctx_doujin.doujin.register_folder(str(make_game(tmp_path, "Same Name")))
    deck_fs.files.update({
        "/deck/doujin/[X] Deck Name RJ333333/Game.exe": "",
        "/deck/doujin/Same Name/Game.exe": "",
    })

    folders = {f.name: f for f in ctx_doujin.doujin.scan_deck()}
    assert folders["[X] Deck Name RJ333333"].match_id == by_id.id
    assert folders["Same Name"].match_id == by_name.id

    result = ctx_doujin.doujin.import_from_deck([f.path for f in folders.values()])
    assert sorted(g.id for g in result) == sorted([by_id.id, by_name.id])
    assert len(ctx_doujin.doujin.list()) == 2
    assert ctx_doujin.doujin.get(by_id.id).deck_dir == "/deck/doujin/[X] Deck Name RJ333333"
