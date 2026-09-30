import pytest

from kakehashi.domain.esde import GameUpdate
from kakehashi.infra.gamelist import Gamelist
from tests.conftest import GAMELIST_PATH, backups


def test_get_games_is_cached_until_refresh(ctx, deck_fs):
    ctx.esde.get_games("ps2")
    ctx.esde.get_games("ps2")
    assert deck_fs.connections == 1
    ctx.esde.get_games("ps2", refresh=True)
    assert deck_fs.connections == 2


def test_find_unregistered_roms_filters_by_metadata_extensions(ctx):
    roms = ctx.esde.find_unregistered_roms("ps2")
    assert [(g.path, g.registered) for g in roms] == [("./c.chd", False)]


def test_update_merges_into_latest_remote_content(ctx, deck_fs):
    ctx.esde.get_games("ps2")
    # UIで読み込んだ後に、Deck側（ES-DE）でお気に入りが付いたケース
    deck_fs.files[GAMELIST_PATH] = deck_fs.files[GAMELIST_PATH].replace(
        "<desc>old</desc>", "<desc>old</desc><favorite>true</favorite>"
    )

    result = ctx.esde.update_games("ps2", [GameUpdate(path="./b.chd", fields={"name": "ゲームB"})])

    assert (result.applied, result.requested) == (1, 1)
    b = Gamelist(deck_fs.files[GAMELIST_PATH]).to_models()[1]
    assert (b.name, b.extra) == ("ゲームB", {"favorite": "true"})
    # キャッシュも書き込み後の内容になる
    assert ctx.esde.get_games("ps2")[1].name == "ゲームB"


def test_update_keeps_limited_backups(ctx, deck_fs, monkeypatch):
    import kakehashi.infra.deck as deck

    stamps = iter(["20260101_000001", "20260101_000002", "20260101_000003"])

    class FakeDatetime:
        @staticmethod
        def now():
            class _T:
                def strftime(self, _fmt):
                    return next(stamps)
            return _T()

    monkeypatch.setattr(deck, "datetime", FakeDatetime)
    for i in range(3):
        ctx.esde.update_games("ps2", [GameUpdate(path="./a.chd", fields={"desc": str(i)})])

    assert [b.rsplit(".", 2)[-2] for b in backups(deck_fs)] == ["20260101_000002", "20260101_000003"]


def test_update_rejects_non_editable_field(ctx):
    with pytest.raises(ValueError):
        ctx.esde.update_games("ps2", [GameUpdate(path="./a.chd", fields={"favorite": "false"})])


def test_update_creates_gamelist_when_missing(ctx, deck_fs):
    del deck_fs.files[GAMELIST_PATH]
    ctx.esde.update_games("ps2", [GameUpdate(path="./c.chd", fields={"name": "C"})])
    assert Gamelist(deck_fs.files[GAMELIST_PATH]).to_models()[0].name == "C"
    assert backups(deck_fs) == []
