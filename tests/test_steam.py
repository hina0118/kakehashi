import struct

import pytest
from PIL import Image

from kakehashi.config import DeckPaths
from kakehashi.domain.doujin import DoujinPatch
from kakehashi.imaging import steam_art
from kakehashi.infra.steam import binary_vdf as bvdf
from kakehashi.infra.steam import text_vdf
from kakehashi.infra.steam.config import get_compat_tool, parse_login_users, set_compat_tool
from kakehashi.infra.steam.shortcuts import ShortcutSpec, Shortcuts, shortcut_appid, to_signed
from kakehashi.services.jobs import Job
from kakehashi.services.steam import SteamRunningError

ROOT = "/home/deck/.local/share/Steam"
UID = "12345678"
SC_PATH = f"{ROOT}/userdata/{UID}/config/shortcuts.vdf"
CFG_PATH = f"{ROOT}/config/config.vdf"
GRID = f"{ROOT}/userdata/{UID}/config/grid"


def cstr(s: str) -> bytes:
    return s.encode() + b"\x00"


def sample_shortcuts() -> bytes:
    """Steamが書いたものを模した shortcuts.vdf（kakehashiが知らない型・キーを含む）。"""
    entry = (
        b"\x02" + cstr("appid") + struct.pack("<i", to_signed(0x9ABCDEF0))
        + b"\x01" + cstr("appname") + cstr("Existing")
        + b"\x01" + cstr("exe") + cstr('"/usr/bin/foo"')
        + b"\x02" + cstr("LastPlayTime") + struct.pack("<i", 1700000000)
        + b"\x03" + cstr("SomeFloat") + struct.pack("<f", 1.5)
        + b"\x07" + cstr("SomeU64") + struct.pack("<Q", 2**40)
        + b"\x00" + cstr("tags") + b"\x01" + cstr("0") + cstr("favorite") + b"\x08"
        + b"\x08"
    )
    return b"\x00" + cstr("shortcuts") + b"\x00" + cstr("0") + entry + b"\x08\x08"


def test_binary_vdf_roundtrip_is_byte_exact():
    data = sample_shortcuts()
    assert bvdf.dumps(bvdf.loads(data)) == data


def test_shortcuts_upsert_keeps_steam_managed_fields():
    sc = Shortcuts(sample_shortcuts())
    spec = ShortcutSpec(appid=0x9ABCDEF0, name="Renamed", exe='"/x/Game.exe"', start_dir='"/x"', launch_options="%command%")
    assert sc.upsert(spec) is False  # 既存を更新

    e = Shortcuts(sc.dumps()).find(0x9ABCDEF0)
    assert e.get("AppName") == "Renamed"
    assert [i.key for i in e.items if i.key.lower() == "appname"] == ["appname"]  # 既存のキー名の綴りを保つ
    assert e.get("LastPlayTime") == 1700000000
    assert e.get("SomeU64") == 2**40
    assert e.get("tags").get("0") == "favorite"

    assert sc.upsert(ShortcutSpec(appid=0x80000001, name="New", exe='"/y"', start_dir='"/"')) is True
    assert [i.key for i in sc._list.items] == ["0", "1"]
    assert sc.remove(0x9ABCDEF0) is True
    assert [i.key for i in sc._list.items] == ["0"]
    assert Shortcuts(sc.dumps()).find(0x80000001).get("AppName") == "New"


def test_shortcuts_created_from_scratch():
    sc = Shortcuts(None)
    sc.upsert(ShortcutSpec(appid=shortcut_appid('"/g/a.exe"', "A"), name="A", exe='"/g/a.exe"', start_dir='"/g"'))
    assert len(Shortcuts(sc.dumps()).entries()) == 1


def test_shortcut_appid_has_high_bit():
    appid = shortcut_appid('"/home/deck/Games/x/Game.exe"', "ゲーム")
    assert appid & 0x80000000 and appid < 2**32
    assert appid == shortcut_appid('"/home/deck/Games/x/Game.exe"', "ゲーム")


CONFIG_VDF = r'''"InstallConfigStore"
{
	// comment
	"Software"
	{
		"Valve"
		{
			"Steam"
			{
				"CompatToolMapping"
				{
					"123"
					{
						"name"		"proton_8"
						"config"		""
						"priority"		"250"
					}
				}
				"Path"		"C:\\Games\\\"quoted\""
				"dup"		"1"
				"dup"		"2"
			}
		}
	}
}
'''


def test_text_vdf_roundtrip_and_compat_mapping():
    kv = text_vdf.loads(CONFIG_VDF)
    steam = kv.path("InstallConfigStore", "Software", "Valve", "Steam")
    assert steam.get("Path") == 'C:\\Games\\"quoted"'
    assert [v for k, v in steam.items if k == "dup"] == ["1", "2"]  # 重複キーを失わない
    assert text_vdf.dumps(text_vdf.loads(text_vdf.dumps(kv))) == text_vdf.dumps(kv)

    set_compat_tool(kv, 2**31 + 5, "proton_experimental")
    assert get_compat_tool(kv, 2**31 + 5) == "proton_experimental"
    assert get_compat_tool(kv, 123) == "proton_8"
    set_compat_tool(kv, 2**31 + 5, "")
    assert get_compat_tool(kv, 2**31 + 5) == ""

    empty = text_vdf.KV()
    set_compat_tool(empty, 1, "proton_9")
    assert get_compat_tool(text_vdf.loads(text_vdf.dumps(empty)), 1) == "proton_9"


def test_parse_login_users():
    kv = text_vdf.loads('"users" { "76561198000000000" { "AccountName" "me" "PersonaName" "私" "MostRecent" "1" } }')
    [u] = parse_login_users(kv)
    assert (u.account_id, u.account_name, u.persona_name, u.most_recent) == ("39734272", "me", "私", True)


def test_steam_art_fits_sizes():
    wide = Image.new("RGB", (560, 420), (200, 0, 0))
    portrait = steam_art.build("portrait", {"cover": wide})
    assert portrait.size == (600, 900)
    # 比率の合わない画像は、元画像を中央に収めて背景を暗くぼかす
    assert portrait.getpixel((300, 450))[0] > 150 and portrait.getpixel((300, 5))[0] < 150
    assert steam_art.build("hero", {"cover": wide}).size == (1920, 620)
    assert steam_art.build("header", {}) is None


# ---- サービス全体 ----

@pytest.fixture
def steam_ctx(ctx, deck_fs, tmp_path):
    ctx.config.steam_deck = DeckPaths(**{**ctx.config.steam_deck.model_dump(), "doujin_base": ["/deck/games"]})
    deck_fs.files.update({
        f"{ROOT}/userdata/{UID}/config/localconfig.vdf": "x",
        f"{ROOT}/config/loginusers.vdf": '"users" { "76561197972611406" { "AccountName" "me" "PersonaName" "わたし" } }',
        CFG_PATH: CONFIG_VDF,
    })
    folder = tmp_path / "Game"
    folder.mkdir()
    (folder / "Game.exe").write_text("x")
    g = ctx.doujin.register_folder(str(folder))
    ctx.doujin.update(g.id, DoujinPatch(title="テストゲーム", deck_dir="/deck/games/Game"))
    cover = tmp_path / "cover.png"
    Image.new("RGB", (560, 420), (0, 120, 200)).save(cover)
    ctx.doujin.import_image_file(g.id, "cover", cover)
    ctx.test_game_id = g.id
    return ctx


def test_apply_registers_shortcut_art_and_proton(steam_ctx, deck_fs):
    gid = steam_ctx.test_game_id
    [r] = steam_ctx.steam.apply([gid], Job("t", "t"))
    assert (r.action, r.error) == ("登録", None)

    entry = Shortcuts(deck_fs.read_bytes(SC_PATH)).find(r.appid)
    assert entry.get("AppName") == "テストゲーム"
    assert entry.get("Exe") == '"/deck/games/Game/Game.exe"'
    assert entry.get("StartDir") == '"/deck/games/Game"'
    assert entry.get("LaunchOptions") == "LANG=ja_JP.UTF-8 %command%"
    assert f"{GRID}/{r.appid}p.png" in deck_fs.files
    assert f"{GRID}/{r.appid}_hero.png" in deck_fs.files
    assert f"{GRID}/{r.appid}_logo.png" not in deck_fs.files
    cfg = text_vdf.loads(deck_fs.read_text(CFG_PATH))
    assert get_compat_tool(cfg, r.appid) == "proton_experimental"
    assert get_compat_tool(cfg, 123) == "proton_8"  # 既存の割り当てを壊さない

    g = steam_ctx.doujin.get(gid)
    assert g.steam_appid == r.appid and g.steam_registered_at is not None


def test_reapply_after_rename_keeps_appid_and_play_time(steam_ctx, deck_fs):
    gid = steam_ctx.test_game_id
    [first] = steam_ctx.steam.apply([gid], Job("t", "t"))
    sc = Shortcuts(deck_fs.read_bytes(SC_PATH))
    sc.find(first.appid).set_int32("LastPlayTime", 1234)  # Steam側で遊んだ記録
    deck_fs.files[SC_PATH] = sc.dumps()

    steam_ctx.doujin.update(gid, DoujinPatch(title="改名後", launch_options="%command% -windowed"))
    [second] = steam_ctx.steam.apply([gid], Job("t", "t"))

    assert (second.appid, second.action) == (first.appid, "更新")
    sc = Shortcuts(deck_fs.read_bytes(SC_PATH))
    assert len(sc.entries()) == 1
    e = sc.find(first.appid)
    assert (e.get("AppName"), e.get("LastPlayTime"), e.get("LaunchOptions")) == ("改名後", 1234, "%command% -windowed")
    assert any(p.startswith(f"{SC_PATH}.") and p.endswith(".bak") for p in deck_fs.files)


def test_refuses_while_steam_running(steam_ctx, deck_fs):
    deck_fs.steam_running = True
    before = dict(deck_fs.files)
    with pytest.raises(SteamRunningError):
        steam_ctx.steam.apply([steam_ctx.test_game_id], Job("t", "t"))
    assert deck_fs.files == before


def test_requires_choosing_among_multiple_accounts(steam_ctx, deck_fs):
    deck_fs.files[f"{ROOT}/userdata/99999/config/localconfig.vdf"] = "x"
    status = steam_ctx.steam.status()
    assert status.user is None and "複数" in status.problem
    with pytest.raises(ValueError):
        steam_ctx.steam.apply([steam_ctx.test_game_id], Job("t", "t"))

    steam_ctx.config.steam_deck.steam_user = UID
    assert steam_ctx.steam.status().user.persona_name == "わたし"


def test_game_errors_are_reported_per_game(steam_ctx):
    g2 = steam_ctx._doujin_db.create({"title": "未転送"})
    results = steam_ctx.steam.apply([steam_ctx.test_game_id, g2["id"]], Job("t", "t"))
    assert [r.error is None for r in results] == [True, False]
    assert "転送" in results[1].error


def test_remove_keeps_appid_for_next_time(steam_ctx, deck_fs):
    gid = steam_ctx.test_game_id
    [r] = steam_ctx.steam.apply([gid], Job("t", "t"))
    steam_ctx.steam.remove([gid], Job("t", "t"))

    assert Shortcuts(deck_fs.read_bytes(SC_PATH)).find(r.appid) is None
    assert f"{GRID}/{r.appid}p.png" not in deck_fs.files
    assert get_compat_tool(text_vdf.loads(deck_fs.read_text(CFG_PATH)), r.appid) == ""
    g = steam_ctx.doujin.get(gid)
    assert g.steam_registered_at is None and g.steam_appid == r.appid
    assert steam_ctx.steam.status().registered_appids == []
