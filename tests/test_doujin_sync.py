"""同人ゲームの作品フォルダを、Deckを正としてPCと同期し、更新データを適用する。"""
import os
from datetime import datetime
from pathlib import Path

import pytest

from kakehashi.config import DeckPaths, LocalPaths
from kakehashi.services.jobs import Job

DECK = "/deck/games/Game"


@pytest.fixture
def sync_ctx(ctx, tmp_path):
    ctx.config.steam_deck = DeckPaths(**{**ctx.config.steam_deck.model_dump(), "doujin_base": ["/deck/games"]})
    ctx.config.windows = LocalPaths(**{**ctx.config.windows.model_dump(), "doujin_base": str(tmp_path / "pc_games")})
    return ctx


@pytest.fixture
def on_deck(sync_ctx, deck_fs):
    """Deckにだけある作品（Steamから取り込んだ状態）。"""
    deck_fs.files.update({
        f"{DECK}/maid/Game.exe": "exe v1",
        f"{DECK}/maid/www/data.json": "data v1",
        f"{DECK}/maid/save/file1.rpgsave": "save 1",
    })
    for p in list(deck_fs.files):
        if p.startswith(DECK):
            deck_fs.touch(p)
    row = sync_ctx._doujin_db.create({"title": "Game", "deck_dir": DECK, "exe": "maid/Game.exe"})
    return row["id"]


def job():
    return Job("t", "t")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_pull_downloads_into_pc_folder_and_only_changes_next_time(sync_ctx, deck_fs, on_deck, tmp_path):
    r = sync_ctx.doujin_sync.pull(on_deck, job())
    local = tmp_path / "pc_games" / "Game"
    assert (r.local_dir, r.downloaded, r.unchanged) == (str(local), 3, 0)
    assert (local / "maid/www/data.json").read_text() == "data v1"
    assert sync_ctx.doujin.get(on_deck).local_path == str(local)
    # 更新日時はDeckと揃えてある
    assert int(os.stat(local / "maid/Game.exe").st_mtime) == deck_fs.mtimes[f"{DECK}/maid/Game.exe"]

    deck_fs.files[f"{DECK}/maid/save/file2.rpgsave"] = "save 2"  # Deckで遊んだ
    deck_fs.touch(f"{DECK}/maid/save/file2.rpgsave")
    r = sync_ctx.doujin_sync.pull(on_deck, job())
    assert (r.downloaded, r.unchanged) == (1, 3)


def test_push_requires_pull_first_for_games_on_deck(sync_ctx, on_deck, tmp_path):
    write(tmp_path / "pc_games" / "Game" / "maid/Game.exe", "exe stale")
    with pytest.raises(ValueError, match="Deckから取得"):
        sync_ctx.doujin_sync.push(on_deck, job())


def test_update_then_push_sends_only_updated_files(sync_ctx, deck_fs, on_deck, tmp_path):
    sync_ctx.doujin_sync.pull(on_deck, job())
    # 更新データ: 作品名_v1.4/maid/... の形で、1段深い
    upd = tmp_path / "dl" / "MyGame_v1.4"
    write(upd / "MyGame_v1.4/maid/Game.exe", "exe v1.4")
    write(upd / "MyGame_v1.4/maid/www/data.json", "data v1")  # 同じ内容
    write(upd / "MyGame_v1.4/maid/www/img/new.png", "png")
    write(upd / "MyGame_v1.4/readme_v1.4.txt", "readme")

    plan = sync_ctx.doujin_sync.plan_update(on_deck, str(upd))
    assert (plan.root, plan.exe_found, plan.version) == ("MyGame_v1.4", True, "1.4")
    assert (plan.new, plan.changed, plan.same) == (2, 1, 1)
    assert {f.path: f.status for f in plan.files} == {
        "maid/Game.exe": "changed", "maid/www/img/new.png": "new", "readme_v1.4.txt": "new",
    }

    res = sync_ctx.doujin_sync.apply_update(on_deck, str(upd), plan.root, plan.version, job())
    assert (res.copied, res.exe_exists) == (3, True)
    assert sync_ctx.doujin.get(on_deck).version == "1.4"

    # 取得のあとDeckでセーブが更新された（PCのセーブは古い）
    deck_fs.files[f"{DECK}/maid/save/file1.rpgsave"] = "save 1 (played)"
    deck_fs.touch(f"{DECK}/maid/save/file1.rpgsave")

    status = sync_ctx.doujin_sync.status(on_deck)
    assert status.local_changed == ["maid/Game.exe", "maid/www/img/new.png", "readme_v1.4.txt"]
    assert status.remote_changed == ["maid/save/file1.rpgsave"]

    r = sync_ctx.doujin_sync.push(on_deck, job())
    assert (r.pushed, r.kept_remote, r.conflicts) == (3, ["maid/save/file1.rpgsave"], [])
    assert deck_fs.files[f"{DECK}/maid/Game.exe"] == "exe v1.4"
    assert deck_fs.files[f"{DECK}/maid/save/file1.rpgsave"] == "save 1 (played)"  # Deckのセーブを守る

    # 反映後は何も送らない
    r = sync_ctx.doujin_sync.push(on_deck, job())
    assert r.pushed == 0


def test_conflict_is_reported_and_force_overwrites(sync_ctx, deck_fs, on_deck, tmp_path):
    sync_ctx.doujin_sync.pull(on_deck, job())
    local = tmp_path / "pc_games" / "Game"
    write(local / "maid/www/data.json", "data edited on pc!")
    deck_fs.files[f"{DECK}/maid/www/data.json"] = "data edited on deck"
    deck_fs.touch(f"{DECK}/maid/www/data.json")

    assert sync_ctx.doujin_sync.status(on_deck).conflicts == ["maid/www/data.json"]
    r = sync_ctx.doujin_sync.push(on_deck, job())
    assert (r.pushed, r.conflicts) == (0, ["maid/www/data.json"])
    assert deck_fs.files[f"{DECK}/maid/www/data.json"] == "data edited on deck"

    # 取得でもPCの変更を勝手に上書きしない
    r = sync_ctx.doujin_sync.pull(on_deck, job())
    assert r.kept_local == ["maid/www/data.json"]

    r = sync_ctx.doujin_sync.push(on_deck, job(), force=True)
    assert r.pushed == 1
    assert deck_fs.files[f"{DECK}/maid/www/data.json"] == "data edited on pc!"


def test_first_push_from_pc_creates_deck_folder(sync_ctx, deck_fs, tmp_path):
    folder = tmp_path / "pc_only" / "New Game"
    write(folder / "Game.exe", "exe")
    g = sync_ctx.doujin.register_folder(str(folder))
    with pytest.raises(ValueError, match="格納先"):
        sync_ctx.doujin_sync.push(g.id, job())
    r = sync_ctx.doujin_sync.push(g.id, job(), base="/deck/games")
    assert (r.deck_dir, r.pushed) == ("/deck/games/New Game", 1)
    assert sync_ctx.doujin.get(g.id).deck_dir == "/deck/games/New Game"
    assert sync_ctx.doujin_sync.push(g.id, job()).pushed == 0


def test_plan_update_without_exe_strips_wrapper_folders(sync_ctx, deck_fs, on_deck, tmp_path):
    sync_ctx.doujin_sync.pull(on_deck, job())
    upd = tmp_path / "patch"
    write(upd / "wrap/inner/maid/www/data.json", "data v2")
    write(upd / "wrap/inner/maid/www/data2.json", "x")
    plan = sync_ctx.doujin_sync.plan_update(on_deck, str(upd))
    # 起動ファイルが無い（差分パッチ）ときは、中身が1つだけの包みのフォルダを外す
    assert (plan.root, plan.exe_found, plan.version) == ("wrap/inner", False, "")
    assert {f.path for f in plan.files} == {"maid/www/data.json", "maid/www/data2.json"}

    with pytest.raises(ValueError):
        sync_ctx.doujin_sync.plan_update(on_deck, str(tmp_path / "pc_games" / "Game"))  # 作品フォルダ自身は不可


def test_plan_update_root_can_be_chosen(sync_ctx, deck_fs, on_deck, tmp_path):
    sync_ctx.doujin_sync.pull(on_deck, job())
    upd = tmp_path / "pkg"
    write(upd / "extras/new_folder/x.txt", "x")
    plan = sync_ctx.doujin_sync.plan_update(on_deck, str(upd))
    # どこにも一致しないので、包みのフォルダを外す
    assert plan.root == "extras/new_folder"
    assert "" in plan.root_candidates and "extras" in plan.root_candidates
    plan = sync_ctx.doujin_sync.plan_update(on_deck, str(upd), root="")
    assert [f.path for f in plan.files] == ["extras/new_folder/x.txt"]
    with pytest.raises(ValueError):
        sync_ctx.doujin_sync.plan_update(on_deck, str(upd), root="nope")


def test_deck_texts_lists_and_decodes_readme(sync_ctx, deck_fs, on_deck):
    deck_fs.files.update({
        f"{DECK}/readme.txt": "はじめに\r\n遊び方".encode("cp932"),
        f"{DECK}/maid/www/更新履歴.md": "## v1.1",
    })
    files = sync_ctx.doujin_sync.deck_texts(on_deck)
    assert [f.path for f in files] == ["readme.txt", "maid/www/更新履歴.md"]

    t = sync_ctx.doujin_sync.read_deck_text(on_deck, "readme.txt")
    assert (t.text, t.encoding, t.truncated) == ("はじめに\r\n遊び方", "Shift_JIS", False)
    assert sync_ctx.doujin_sync.read_deck_text(on_deck, "maid/www/更新履歴.md").encoding == "UTF-8"


@pytest.mark.parametrize("rel", ["../other/readme.txt", "/etc/passwd.txt", "maid/Game.exe"])
def test_read_deck_text_rejects_paths_outside_texts(sync_ctx, on_deck, rel):
    with pytest.raises(ValueError):
        sync_ctx.doujin_sync.read_deck_text(on_deck, rel)


def test_decode_text_tolerates_cut_multibyte_char_when_truncated():
    from kakehashi.services.doujin_sync import decode_text
    data = "日本語".encode("utf-8")[:-1]
    assert decode_text(data, truncated=True) == ("日本", "UTF-8")


def test_check_deck_finds_deleted_folders_and_missing_exe(sync_ctx, deck_fs, on_deck):
    db = sync_ctx._doujin_db
    deck_fs.files["/deck/games/Other/Game.exe"] = "exe"
    renamed = db.create({"title": "Renamed", "deck_dir": "/deck/games/Other", "exe": "Old.exe"})["id"]
    deleted = db.create({"title": "Deleted", "deck_dir": "/deck/games/Gone", "exe": "Game.exe"})["id"]
    db.update(deleted, {"steam_appid": 123, "steam_registered_at": datetime.now()})
    no_sd = db.create({"title": "SD", "deck_dir": "/run/media/sd/Games/X", "exe": "Game.exe"})["id"]

    r = sync_ctx.doujin_sync.check_deck()
    assert r.checked == 4
    assert {(p.id, p.status, p.steam_registered) for p in r.problems} == {
        (renamed, "exe_missing", False), (deleted, "folder_missing", True), (no_sd, "unreachable", False),
    }


def test_unlink_deck_clears_deck_dir_and_snapshot_only_for_deleted_folders(sync_ctx, deck_fs, on_deck):
    sync_ctx.doujin_sync.pull(on_deck, job())
    with pytest.raises(ValueError, match="まだDeckにあります"):
        sync_ctx.doujin_sync.unlink_deck([on_deck])

    for p in [p for p in deck_fs.files if p.startswith(DECK)]:
        del deck_fs.files[p]  # Deck上でフォルダごと削除
    deck_fs.files["/deck/games/Another/Game.exe"] = "exe"  # 格納先自体は残っている
    assert sync_ctx.doujin_sync.unlink_deck([on_deck]) == [on_deck]
    g = sync_ctx.doujin.get(on_deck)
    assert (g.deck_dir, bool(g.local_path)) == ("", True)
    assert sync_ctx.doujin_sync.status(on_deck).synced_before is False


def test_unlink_deck_refuses_when_storage_is_missing(sync_ctx, deck_fs, on_deck):
    deck_fs.files.clear()  # SDカードが抜けている
    with pytest.raises(ValueError, match="SDカード"):
        sync_ctx.doujin_sync.unlink_deck([on_deck])


@pytest.fixture
def two_bases(sync_ctx, deck_fs, on_deck):
    sync_ctx.config.steam_deck = DeckPaths(**{**sync_ctx.config.steam_deck.model_dump(), "doujin_base": ["/deck/games", "/sd/games"]})
    deck_fs.files["/sd/games/Other/a.exe"] = "x"
    return sync_ctx


def test_move_keeps_snapshot_valid(two_bases, deck_fs, on_deck):
    two_bases.doujin_sync.pull(on_deck, job())
    r = two_bases.doujin_sync.move(on_deck, "/sd/games", job())
    assert (r.deck_dir, r.cross_device) == ("/sd/games/Game", False)
    assert "/sd/games/Game/maid/Game.exe" in deck_fs.files and f"{DECK}/maid/Game.exe" not in deck_fs.files
    assert two_bases.doujin.get(on_deck).deck_dir == "/sd/games/Game"
    s = two_bases.doujin_sync.status(on_deck)  # 更新日時も移るので、差分は出ない
    assert (s.local_changed, s.remote_changed, s.conflicts) == ([], [], [])


def test_move_refuses_unsafe_moves(two_bases, deck_fs, on_deck):
    with pytest.raises(ValueError, match="すでに"):
        two_bases.doujin_sync.move(on_deck, "/deck/games")
    with pytest.raises(ValueError, match="設定にない"):
        two_bases.doujin_sync.move(on_deck, "/tmp")
    deck_fs.disks = {"/deck/": (1, 10**12), "/sd/": (2, 10)}  # 別のドライブで空きが足りない
    with pytest.raises(ValueError, match="空き容量"):
        two_bases.doujin_sync.move(on_deck, "/sd/games")
    deck_fs.disks = {}
    deck_fs.files["/sd/games/Game/x"] = "x"
    with pytest.raises(ValueError, match="同じ名前"):
        two_bases.doujin_sync.move(on_deck, "/sd/games")
    assert f"{DECK}/maid/Game.exe" in deck_fs.files


def test_status_reports_missing_pc_folder(sync_ctx, on_deck, tmp_path):
    import shutil
    sync_ctx.doujin_sync.pull(on_deck, job())
    assert sync_ctx.doujin_sync.status(on_deck).local_exists is True
    shutil.rmtree(tmp_path / "pc_games" / "Game")
    assert sync_ctx.doujin_sync.status(on_deck).local_exists is False
    sync_ctx.doujin_sync.pull(on_deck, job())  # Deckから取り直せる
    assert (tmp_path / "pc_games" / "Game" / "maid/Game.exe").read_text() == "exe v1"
