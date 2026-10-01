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


# ---- 既存のSteam登録との共存（実機の登録内容を模したもの） ----

WIN = "/home/deck/Documents/wingames"


def existing_steam(deck_fs, entries):
    """手動などで登録済みの shortcuts.vdf・Proton設定・画像を用意する。"""
    sc = Shortcuts(None)
    kv = text_vdf.loads(CONFIG_VDF)
    for appid, name, exe, tool, launch in entries:
        sc.upsert(ShortcutSpec(appid=appid, name=name, exe=exe, start_dir=exe.strip('"').rsplit("/", 1)[0] + "/",
                               launch_options=launch))
        if tool:
            set_compat_tool(kv, appid, tool)
    deck_fs.files[SC_PATH] = sc.dumps()
    deck_fs.files[CFG_PATH] = text_vdf.dumps(kv)


@pytest.fixture
def real_like(steam_ctx, deck_fs):
    steam_ctx.config.steam_deck = DeckPaths(**{**steam_ctx.config.steam_deck.model_dump(), "doujin_base": [WIN]})
    existing_steam(deck_fs, [
        (3748535911, "★アルム冒険者団", f'"{WIN}/アルム_v1_5/Game.exe"', "GE-Proton9-14", ""),
        (2422716232, "★tratrittle", f'"{WIN}/tratrittle_v1.3.4/maid/Game.exe"', "GE-Proton9-27", ""),
        (2800000000, "Outside", '"/home/deck/Documents/drm/作品A/sub/a.exe"', "GE-Proton9-16", ""),
        (2800000001, "Outside2", '"/home/deck/Documents/drm/作品B/b.exe"', "", ""),
        (3373760206, "ES-DE", '"/run/media/deck/SR01T/Emulation/tools/launchers/es-de.sh"', "", "LANG=ja_JP.UTF-8 %command%"),
    ])
    deck_fs.files[f"{GRID}/2422716232p.jpg"] = b"user art"
    return steam_ctx


def test_scan_shortcuts_lists_windows_games_and_splits_paths(real_like):
    scan = real_like.steam.scan_shortcuts()
    by = {s.appid: s for s in scan.shortcuts}
    assert 3373760206 not in by  # .sh（エミュレータのランチャー）は対象外
    t = by[2422716232]
    assert (t.deck_dir, t.exe, t.in_base, t.compat_tool, t.has_art) == (
        f"{WIN}/tratrittle_v1.3.4", "maid/Game.exe", True, "GE-Proton9-27", True,
    )
    o = by[2800000000]
    assert (o.deck_dir, o.exe, o.in_base) == ("/home/deck/Documents/drm/作品A/sub", "a.exe", False)
    assert scan.suggested_bases == ["/home/deck/Documents/drm"]


def test_import_shortcuts_keeps_appid_proton_and_links_existing(real_like, deck_fs):
    # 台帳に同じ作品がある（Deckから取り込んだが、まだSteamと紐づいていない）
    linked = real_like._doujin_db.create({"title": "アルム", "deck_dir": f"{WIN}/アルム_v1_5", "exe": "Game.exe"})

    games = real_like.steam.import_shortcuts([3748535911, 2422716232])
    by = {g.steam_appid: g for g in games}
    assert by[3748535911].id == linked["id"]  # 新規に作らず紐づけ
    assert by[3748535911].title == "アルム"  # 台帳のタイトルはそのまま
    t = by[2422716232]
    assert (t.title, t.deck_dir, t.exe, t.compat_tool) == ("★tratrittle", f"{WIN}/tratrittle_v1.3.4", "maid/Game.exe", "GE-Proton9-27")
    assert t.steam_registered_at is not None

    # 取り込み済みのものは一覧で「台帳にあり」になり、再度取り込んでも増えない
    assert real_like.steam.import_shortcuts([2422716232]) == []


def test_register_adopts_existing_entry_by_exe(real_like, deck_fs):
    """台帳の作品がSteamに手動登録済みなら、そのエントリを引き継いで更新する（二重登録しない）。"""
    g = real_like._doujin_db.create({"title": "tratrittle", "deck_dir": f"{WIN}/tratrittle_v1.3.4", "exe": "maid/Game.exe"})
    sc = Shortcuts(deck_fs.read_bytes(SC_PATH))
    sc.find(2422716232).set_int32("LastPlayTime", 999)
    deck_fs.files[SC_PATH] = sc.dumps()
    before = len(sc.entries())

    [r] = real_like.steam.apply([g["id"]], Job("t", "t"))

    assert (r.appid, r.action) == (2422716232, "既存の登録を引き継いで更新")
    sc = Shortcuts(deck_fs.read_bytes(SC_PATH))
    assert len(sc.entries()) == before
    e = sc.find(2422716232)
    assert (e.get("AppName"), e.get("LastPlayTime"), e.get("LaunchOptions")) == ("tratrittle", 999, "")
    # 作品ごとに選んだProtonを既定値で上書きしない
    assert get_compat_tool(text_vdf.loads(deck_fs.read_text(CFG_PATH)), 2422716232) == "GE-Proton9-27"
    assert real_like.doujin.get(g["id"]).steam_appid == 2422716232


def test_existing_art_is_kept_unless_overwrite(real_like, deck_fs, tmp_path):
    g = real_like._doujin_db.create({"title": "tratrittle", "deck_dir": f"{WIN}/tratrittle_v1.3.4", "exe": "maid/Game.exe"})
    cover = tmp_path / "c.png"
    Image.new("RGB", (600, 900), (10, 200, 10)).save(cover)
    real_like.doujin.import_image_file(g["id"], "cover", cover)

    real_like.steam.apply([g["id"]], Job("t", "t"))
    assert deck_fs.files[f"{GRID}/2422716232p.jpg"] == b"user art"  # 既存の画像を残す
    assert f"{GRID}/2422716232p.png" not in deck_fs.files
    assert f"{GRID}/2422716232.png" in deck_fs.files  # 無かった種類は書き込む

    real_like.steam.apply([g["id"]], Job("t", "t"), overwrite_art=True)
    assert f"{GRID}/2422716232p.png" in deck_fs.files
    assert f"{GRID}/2422716232p.jpg" not in deck_fs.files  # 拡張子違いの古い画像は片付ける


def test_art_without_source_is_not_deleted(real_like, deck_fs):
    g = real_like._doujin_db.create({"title": "t", "deck_dir": f"{WIN}/tratrittle_v1.3.4", "exe": "maid/Game.exe"})
    real_like.steam.apply([g["id"]], Job("t", "t"), overwrite_art=True)
    assert deck_fs.files[f"{GRID}/2422716232p.jpg"] == b"user art"


def test_appid_used_by_other_catalog_entry_is_rejected(real_like):
    a = real_like._doujin_db.create({"title": "A", "deck_dir": f"{WIN}/tratrittle_v1.3.4", "exe": "maid/Game.exe"})
    b = real_like._doujin_db.create({"title": "B", "deck_dir": f"{WIN}/tratrittle_v1.3.4", "exe": "maid/Game.exe"})
    ra, rb = real_like.steam.apply([a["id"], b["id"]], Job("t", "t"))
    assert ra.error is None and "「A」" in rb.error


# ---- Steamに設定済みの画像を台帳へ取り込む ----

def image_bytes(fmt: str, size=(40, 60), color=(200, 30, 30)) -> bytes:
    import io
    buf = io.BytesIO()
    img = Image.new("RGBA" if fmt == "ICO" else "RGB", size, color)
    img.save(buf, fmt, **({"sizes": [(16, 16), (48, 48)]} if fmt == "ICO" else {}))
    return buf.getvalue()


@pytest.fixture
def with_grid(real_like, deck_fs):
    deck_fs.files.update({
        f"{GRID}/2422716232p.jpg": image_bytes("JPEG", (600, 900)),
        f"{GRID}/2422716232p.png": image_bytes("PNG", (600, 900), (0, 0, 200)),  # 同じ種類が2つ（PNGを優先）
        f"{GRID}/2422716232_hero.jpg": image_bytes("JPEG", (1920, 620)),
        f"{GRID}/2422716232_icon.ico": image_bytes("ICO", (48, 48)),
    })
    return real_like


def test_grid_images_lists_steam_art_for_unlinked_game(with_grid):
    # 台帳にappIDが無くても、起動ファイルで Steam の登録を見つける
    g = with_grid._doujin_db.create({"title": "t", "deck_dir": f"{WIN}/tratrittle_v1.3.4", "exe": "maid/Game.exe"})
    images = {i.kind: i.filename for i in with_grid.steam.grid_images(g["id"])}
    assert images == {"cover": "2422716232p.png", "hero": "2422716232_hero.jpg", "icon": "2422716232_icon.ico"}
    data, ext = with_grid.steam.grid_image_bytes(g["id"], "hero")
    assert ext == ".jpg" and data[:2] == b"\xff\xd8"


def test_pull_art_fills_missing_kinds_and_converts_ico(with_grid, tmp_path):
    g = with_grid._doujin_db.create({"title": "t", "deck_dir": f"{WIN}/tratrittle_v1.3.4", "exe": "maid/Game.exe"})
    mine = tmp_path / "mine.png"
    Image.new("RGB", (10, 10), (0, 255, 0)).save(mine)
    with_grid.doujin.import_image_file(g["id"], "hero", mine)  # 台帳に既にある種類

    [r] = with_grid.steam.pull_art([g["id"]])
    assert (sorted(r.imported), r.skipped, r.error) == (["cover", "icon"], ["hero"], None)
    game = with_grid.doujin.get(g["id"])
    assert game.images["icon"].filename == "icon.png"  # .ico は PNG に変換
    assert game.images["cover"].filename == "cover.png"
    with Image.open(with_grid.doujin.image_path(g["id"], "icon")) as icon:
        assert icon.size == (48, 48)  # いちばん大きいサイズを使う
    with Image.open(with_grid.doujin.image_path(g["id"], "hero")) as hero:
        assert hero.size == (10, 10)  # 上書きしない

    [r] = with_grid.steam.pull_art([g["id"]], kinds=["hero"], overwrite=True)
    assert r.imported == ["hero"]
    assert with_grid.doujin.get(g["id"]).images["hero"].filename == "hero.jpg"


def test_pull_art_reports_unregistered(with_grid):
    g = with_grid._doujin_db.create({"title": "未登録", "deck_dir": f"{WIN}/none", "exe": "Game.exe"})
    [r] = with_grid.steam.pull_art([g["id"]])
    assert "登録されていない" in r.error


def test_icon_field_outside_grid_is_used(with_grid, deck_fs):
    sc = Shortcuts(deck_fs.read_bytes(SC_PATH))
    sc.find(3748535911).set_str("icon", f'"{WIN}/アルム_v1_5/icon.ico"')
    deck_fs.files[SC_PATH] = sc.dumps()
    deck_fs.files[f"{WIN}/アルム_v1_5/icon.ico"] = image_bytes("ICO", (48, 48))
    g = with_grid._doujin_db.create({"title": "a", "deck_dir": f"{WIN}/アルム_v1_5", "exe": "Game.exe"})
    assert {i.kind: i.filename for i in with_grid.steam.grid_images(g["id"])} == {"icon": f"{WIN}/アルム_v1_5/icon.ico"}
    [r] = with_grid.steam.pull_art([g["id"]])
    assert r.imported == ["icon"]


# ---- Steamに反映するときの画像の更新判定 ----

def statuses(result) -> dict[str, str]:
    return dict(result.art)


def test_art_written_once_then_skipped_until_catalog_changes(steam_ctx, deck_fs, tmp_path):
    gid = steam_ctx.test_game_id
    [r] = steam_ctx.steam.apply([gid], Job("t", "t"))
    assert statuses(r) == {"portrait": "new", "header": "new", "hero": "new", "logo": "no_source", "icon": "no_source"}
    portrait = f"{GRID}/{r.appid}p.png"
    first_mtime = deck_fs.mtimes[portrait]

    [r] = steam_ctx.steam.apply([gid], Job("t", "t"))
    assert statuses(r)["portrait"] == "same"
    assert deck_fs.mtimes[portrait] == first_mtime  # 書き直していない

    # 台帳のカバーを差し替えると、カバーから作る種類だけ書き込む
    cover = tmp_path / "new_cover.png"
    Image.new("RGB", (600, 900), (1, 2, 3)).save(cover)
    steam_ctx.doujin.import_image_file(gid, "cover", cover)
    logo = tmp_path / "logo.png"
    Image.new("RGBA", (300, 100), (9, 9, 9, 255)).save(logo)
    steam_ctx.doujin.import_image_file(gid, "logo", logo)
    [r] = steam_ctx.steam.apply([gid], Job("t", "t"))
    assert statuses(r) == {"portrait": "updated", "header": "updated", "hero": "updated", "logo": "new", "icon": "no_source"}
    assert deck_fs.mtimes[portrait] > first_mtime


def test_steam_side_changes_are_kept(steam_ctx, deck_fs, tmp_path):
    gid = steam_ctx.test_game_id
    [r] = steam_ctx.steam.apply([gid], Job("t", "t"))
    portrait, hero = f"{GRID}/{r.appid}p.png", f"{GRID}/{r.appid}_hero.png"
    # 利用者がSteamでカバーを設定し直した
    deck_fs.files[portrait] = b"set in steam"
    deck_fs.touch(portrait)

    [r] = steam_ctx.steam.apply([gid], Job("t", "t"))
    assert statuses(r)["portrait"] == "steam_changed"
    assert deck_fs.files[portrait] == b"set in steam"

    # 台帳側も変えると「両方で変更」。既定ではSteam側を残し、置き換えを選ぶと書き込む
    cover = tmp_path / "c2.png"
    Image.new("RGB", (600, 900), (5, 5, 5)).save(cover)
    steam_ctx.doujin.import_image_file(gid, "cover", cover)
    deck_fs.touch(hero)
    [r] = steam_ctx.steam.apply([gid], Job("t", "t"))
    assert (statuses(r)["portrait"], statuses(r)["hero"], statuses(r)["header"]) == ("conflict", "conflict", "updated")
    assert deck_fs.files[portrait] == b"set in steam"

    [r] = steam_ctx.steam.apply([gid], Job("t", "t"), overwrite_art=True)
    assert statuses(r)["portrait"] == "forced"
    assert deck_fs.files[portrait] != b"set in steam"
    [r] = steam_ctx.steam.apply([gid], Job("t", "t"))
    assert statuses(r)["portrait"] == "same"


def test_pulled_art_is_not_written_back(with_grid, deck_fs):
    g = with_grid._doujin_db.create({"title": "t", "deck_dir": f"{WIN}/tratrittle_v1.3.4", "exe": "maid/Game.exe"})
    with_grid.steam.pull_art([g["id"]])
    before = dict(deck_fs.mtimes)

    status = {d.slot: d.status for d in with_grid.steam.art_status(g["id"])}
    # 取り込んだ種類は「変更なし」。ヘッダーはSteamに無いので、台帳のヒーローから作って新しく書き込む
    assert status == {"portrait": "same", "header": "new", "hero": "same", "logo": "no_source", "icon": "same"}

    [r] = with_grid.steam.apply([g["id"]], Job("t", "t"))
    assert statuses(r)["portrait"] == "same"
    assert deck_fs.mtimes.get(f"{GRID}/2422716232p.png") == before.get(f"{GRID}/2422716232p.png")
    assert deck_fs.files[f"{GRID}/2422716232_icon.ico"]  # Steamで設定したアイコン（.ico）は書き換えない


def test_remove_clears_art_records(steam_ctx):
    gid = steam_ctx.test_game_id
    steam_ctx.steam.apply([gid], Job("t", "t"))
    assert steam_ctx._doujin_db.art_states(gid)
    steam_ctx.steam.remove([gid], Job("t", "t"))
    assert steam_ctx._doujin_db.art_states(gid) == {}
