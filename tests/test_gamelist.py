from kakehashi.infra.gamelist import Gamelist
from tests.conftest import SAMPLE_GAMELIST


def test_parse_keeps_extra_tags_readonly():
    games = Gamelist(SAMPLE_GAMELIST).to_models()
    assert [g.path for g in games] == ["./a.chd", "./b.chd"]
    assert games[0].name == "Game A"
    assert games[0].extra == {"favorite": "true"}


def test_apply_updates_only_given_fields_and_keeps_unknown_tags():
    gl = Gamelist(SAMPLE_GAMELIST)
    applied, deleted = gl.apply({"./a.chd": {"desc": "説明", "name": "ゲームA"}})
    assert (applied, deleted) == (1, 0)

    reparsed = Gamelist(gl.serialize())
    a = reparsed.to_models()[0]
    assert (a.name, a.desc, a.extra) == ("ゲームA", "説明", {"favorite": "true"})
    assert "<alternativeEmulator>" in gl.serialize()


def test_apply_empty_value_removes_tag():
    gl = Gamelist(SAMPLE_GAMELIST)
    gl.apply({"./b.chd": {"desc": ""}})
    assert "<desc>" not in gl.serialize()


def test_apply_adds_unknown_path_and_deletes():
    gl = Gamelist(SAMPLE_GAMELIST)
    applied, deleted = gl.apply({"./c.chd": {"name": "Game C"}}, {"./b.chd"})
    assert (applied, deleted) == (1, 1)
    assert [g.path for g in gl.to_models()] == ["./a.chd", "./c.chd"]


def test_parse_without_gamelist_element():
    gl = Gamelist('<?xml version="1.0"?>\n<alternativeEmulator><label>x</label></alternativeEmulator>')
    assert gl.to_models() == []
    gl.apply({"./x.iso": {"name": "X"}})
    assert gl.to_models()[0].name == "X"
