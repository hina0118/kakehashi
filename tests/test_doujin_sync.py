"""同人ゲームの作品フォルダを、Deckを正としてPCと同期し、更新データを適用する。"""
import os
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
