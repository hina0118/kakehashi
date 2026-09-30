from pathlib import Path

import pytest
from PIL import Image

from kakehashi.errors import NotFoundError
from kakehashi.services.jobs import Job

GAME = "./Game [USA] (Disc 1).chd"
STEM = "Game [USA] (Disc 1)"


@pytest.fixture
def media_dir(ctx) -> Path:
    return Path(ctx.config.windows.media_base) / "ps2"


def put(base: Path, folder: str, name: str, text: str = "x") -> Path:
    p = base / folder / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def job() -> Job:
    return Job("test", "test")


def test_game_media_matches_stem_with_glob_characters(ctx, media_dir):
    put(media_dir, "covers", f"{STEM}.png")
    put(media_dir, "covers", "Game U.png")  # "[USA]" をglobの文字クラスと解釈すると誤って一致する名前
    media = ctx.media.game_media("ps2", GAME)
    assert media.files["covers"].filename == f"{STEM}.png"
    assert media.files["screenshots"] is None
    assert ctx.media.coverage("ps2")[STEM] == {"covers": f"{STEM}.png"}


def test_replacing_with_other_extension_schedules_remote_deletion(ctx, media_dir, deck_fs, tmp_path):
    put(media_dir, "covers", f"{STEM}.jpg")
    src = put(tmp_path, "src", "new.PNG", "new")

    saved = ctx.media.import_file("ps2", GAME, "covers", src)

    assert saved.filename == f"{STEM}.png"
    assert not (media_dir / "covers" / f"{STEM}.jpg").exists()
    assert ctx.media.pending_deletions("ps2") == [f"covers/{STEM}.jpg"]

    deck_fs.files[f"/deck/media/ps2/covers/{STEM}.jpg"] = "old"
    result = ctx.media.push("ps2", job())
    assert (result.deleted, result.transferred) == (1, 1)
    assert f"/deck/media/ps2/covers/{STEM}.jpg" not in deck_fs.files
    assert deck_fs.files[f"/deck/media/ps2/covers/{STEM}.png"] == "new"
    assert ctx.media.pending_deletions("ps2") == []


def test_deleted_media_is_not_pulled_back(ctx, media_dir, deck_fs):
    put(media_dir, "videos", f"{STEM}.mp4")
    deck_fs.files[f"/deck/media/ps2/videos/{STEM}.mp4"] = "x"

    assert ctx.media.delete("ps2", GAME, "videos") == 1
    ctx.media.pull("ps2", job())
    assert not (media_dir / "videos" / f"{STEM}.mp4").exists()

    ctx.media.push("ps2", job())
    assert f"/deck/media/ps2/videos/{STEM}.mp4" not in deck_fs.files


def test_pull_fetches_missing_but_keeps_local_edits(ctx, media_dir, deck_fs):
    put(media_dir, "3dboxes", "a.png", "edited locally")
    put(media_dir, "covers", "a.jpg", "local jpg")
    deck_fs.files.update({
        "/deck/media/ps2/3dboxes/a.png": "deck version",
        "/deck/media/ps2/covers/a.png": "deck png",  # 同じゲームの covers はPCに別拡張子で存在
        "/deck/media/ps2/screenshots/a.png": "shot",
    })

    result = ctx.media.pull("ps2", job())

    assert result.transferred == 1
    assert (media_dir / "screenshots" / "a.png").read_text() == "shot"
    assert (media_dir / "3dboxes" / "a.png").read_text() == "edited locally"
    assert not (media_dir / "covers" / "a.png").exists()

    ctx.media.pull("ps2", job(), overwrite=True)
    assert (media_dir / "3dboxes" / "a.png").read_text() == "deck version"


def test_push_sends_only_changed_files(ctx, media_dir, deck_fs):
    put(media_dir, "covers", "a.png", "same")
    put(media_dir, "covers", "b.png", "changed!")
    deck_fs.files["/deck/media/ps2/covers/a.png"] = "same"
    deck_fs.files["/deck/media/ps2/covers/b.png"] = "old"

    result = ctx.media.push("ps2", job())

    assert (result.transferred, result.skipped) == (1, 1)
    assert deck_fs.files["/deck/media/ps2/covers/b.png"] == "changed!"


def test_file_path_rejects_traversal(ctx, media_dir):
    put(media_dir, "covers", "a.png")
    with pytest.raises(ValueError):
        ctx.media.file_path("ps2", "covers", "../covers/a.png")
    with pytest.raises(ValueError):
        ctx.media.file_path("ps2", "../../etc", "a.png")
    with pytest.raises(NotFoundError):
        ctx.media.file_path("ps2", "covers", "missing.png")


def test_generate_3dbox_and_miximage_then_save(ctx, media_dir):
    (media_dir / "covers").mkdir(parents=True)
    (media_dir / "screenshots").mkdir(parents=True)
    Image.new("RGB", (200, 280), (200, 40, 40)).save(media_dir / "covers" / f"{STEM}.png")
    Image.new("RGB", (320, 240), (40, 40, 200)).save(media_dir / "screenshots" / f"{STEM}.png")

    box = ctx.media.preview_3dbox("ps2", GAME, spine_text="テスト")
    ctx.media.save_preview("ps2", GAME, "3dboxes", box.id)
    assert Image.open(media_dir / "3dboxes" / f"{STEM}.png").mode == "RGBA"

    mix = ctx.media.preview_miximage("ps2", GAME)
    assert (mix.width, mix.height) == (1280, 960)

    crop = ctx.media.preview_crop("ps2", GAME, "covers", (10, 10, 110, 60))
    assert (crop.width, crop.height) == (100, 50)


def test_miximage_requires_screenshot(ctx, media_dir):
    with pytest.raises(NotFoundError):
        ctx.media.preview_miximage("ps2", GAME)


def test_upload_roms_appear_as_unregistered(ctx, deck_fs, tmp_path):
    rom = put(tmp_path, "roms", "new.iso", "rom")
    result = ctx.esde.upload_roms("ps2", [rom], job())
    assert result["transferred"] == 1
    assert "./new.iso" in [g.path for g in ctx.esde.find_unregistered_roms("ps2")]
