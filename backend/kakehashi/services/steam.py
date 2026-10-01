"""同人ゲームを Steam Deck の Steam に非Steamゲームとして登録する。

書き込むもの（すべてSteamが停止している間に限る）:
  userdata/<アカウント>/config/shortcuts.vdf   非Steamゲームの一覧
  userdata/<アカウント>/config/grid/           ライブラリ画像
  config/config.vdf                             互換ツール（Proton）の割り当て
Steam は起動中これらをメモリに保持し、終了時に書き戻すため、起動中に書いても消えてしまう。
"""
from __future__ import annotations

import io
import posixpath
from datetime import datetime
from typing import Callable

from PIL import Image
from pydantic import BaseModel

from kakehashi.config import Config
from kakehashi.domain.doujin import DoujinGame, guess_from_folder_name
from kakehashi.imaging import steam_art
from kakehashi.infra.deck import DeckConnector, TransferFS, write_with_backup
from kakehashi.infra.doujin_db import DoujinDB
from kakehashi.infra.steam import text_vdf
from kakehashi.infra.steam.config import SteamUser, get_compat_tool, parse_login_users, set_compat_tool
from kakehashi.infra.steam.shortcuts import (
    ShortcutSpec, Shortcuts, entry_appid, normalize_path, quote, shortcut_appid,
)
from kakehashi.errors import NotFoundError
from kakehashi.services.doujin import DoujinService
from kakehashi.services.jobs import Job

# Steam のグリッド画像のファイル名（{appid} に続く部分。拡張子は png/jpg などいずれも使われる）
_GRID_STEMS = {"portrait": "p", "header": "", "hero": "_hero", "logo": "_logo", "icon": "_icon"}
_GRID_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".ico")
_WINDOWS_SUFFIXES = (".exe", ".bat", ".msi", ".lnk")

BUILTIN_COMPAT_TOOLS = ["proton_experimental", "proton_hotfix", "proton_9", "proton_8", "proton_7"]


class SteamRunningError(RuntimeError):
    """Steamが起動中のため書き込めない。"""


class SteamStatus(BaseModel):
    running: bool
    users: list[SteamUser]
    user: SteamUser | None
    problem: str | None = None
    registered_appids: list[int] = []
    """shortcuts.vdf に実際に載っている非Steamゲームの appID。"""


class SteamShortcut(BaseModel):
    """Deckの shortcuts.vdf に登録されている非Steamゲーム（Windows用のもの）。"""
    appid: int
    name: str
    exe_path: str
    launch_options: str = ""
    compat_tool: str = ""
    has_art: bool = False
    deck_dir: str
    """推定した作品フォルダ（格納先の直下のフォルダ。格納先の外なら起動ファイルのあるフォルダ）"""
    exe: str
    """作品フォルダからの起動ファイルの相対パス"""
    in_base: bool
    linked_id: int | None = None
    """このappIDを持つ台帳の作品"""
    match_id: int | None = None
    """まだSteamと紐づいていない台帳の作品のうち、同じ起動ファイルを指すもの（取り込むと紐づける）"""


class SteamScan(BaseModel):
    shortcuts: list[SteamShortcut]
    suggested_bases: list[str]
    """格納先に登録されていないが、複数の作品が置かれているフォルダ"""


class GridImage(BaseModel):
    """Deck の Steam に設定されているライブラリ画像（1種類分）。"""
    kind: str
    """台帳の画像の種類（cover / header / hero / logo / icon）"""
    filename: str
    """grid フォルダ内のファイル名。アイコン欄が grid の外を指すときはそのパス"""
    in_catalog: bool
    """台帳に同じ種類の画像が既にあるか"""


class ArtPullResult(BaseModel):
    id: int
    title: str
    imported: list[str] = []
    skipped: list[str] = []
    """台帳に既にあるため取り込まなかった種類"""
    error: str | None = None


class SteamGameResult(BaseModel):
    id: int
    title: str
    appid: int | None = None
    action: str = ""
    error: str | None = None


class SteamService:
    def __init__(
        self, get_config: Callable[[], Config], connect: DeckConnector,
        doujin: DoujinService, db: DoujinDB,
    ) -> None:
        self._get_config = get_config
        self._connect = connect
        self._doujin = doujin
        self._db = db

    # ---- 状態 ----

    def _root(self) -> str:
        return self._get_config().steam_deck.steam_root.rstrip("/")

    def _is_running(self, fs: TransferFS) -> bool:
        _code, out, _err = fs.run("pgrep -x steam >/dev/null && echo running || echo stopped")
        return "running" in out

    def _users(self, fs: TransferFS) -> list[SteamUser]:
        root = self._root()
        dirs = [d for d in fs.list_dirs(f"{root}/userdata") if d.isdigit() and d != "0"]
        known: dict[str, SteamUser] = {}
        try:
            for u in parse_login_users(text_vdf.loads(fs.read_text(f"{root}/config/loginusers.vdf"))):
                known[u.account_id] = u
        except (FileNotFoundError, ValueError):
            pass
        return [known.get(d, SteamUser(account_id=d)) for d in dirs]

    def _resolve_user(self, users: list[SteamUser]) -> SteamUser:
        wanted = self._get_config().steam_deck.steam_user
        if wanted:
            user = next((u for u in users if u.account_id == wanted), None)
            if user is None:
                raise ValueError(f"設定されたSteamアカウント（{wanted}）がDeckに見つかりません。")
            return user
        if len(users) == 1:
            return users[0]
        if not users:
            raise ValueError("DeckにSteamのユーザーデータが見つかりません。一度Steamにログインしてください。")
        raise ValueError("Deckに複数のSteamアカウントがあります。設定画面で登録先のアカウントを選んでください。")

    def status(self) -> SteamStatus:
        with self._connect() as fs:
            running = self._is_running(fs)
            users = self._users(fs)
            try:
                user = self._resolve_user(users)
            except ValueError as e:
                return SteamStatus(running=running, users=users, user=None, problem=str(e))
            appids: list[int] = []
            path = self._shortcuts_path(user)
            if fs.exists(path):
                sc = Shortcuts(fs.read_bytes(path))
                appids = [int(e.get("appid")) & 0xFFFFFFFF for e in sc.entries() if isinstance(e.get("appid"), int)]
        return SteamStatus(running=running, users=users, user=user, registered_appids=appids)

    def compat_tools(self) -> list[str]:
        """選べる互換ツール名。Steam同梱のProtonと、compatibilitytools.d に入れたもの（GE-Protonなど）。"""
        with self._connect() as fs:
            custom = fs.list_dirs(f"{self._root()}/compatibilitytools.d")
        return BUILTIN_COMPAT_TOOLS + [c for c in custom if c not in BUILTIN_COMPAT_TOOLS]

    # ---- Steamに登録済みの非Steamゲームの取り込み ----

    def scan_shortcuts(self) -> SteamScan:
        """Deckの shortcuts.vdf から、Windows用の非Steamゲームを列挙する（読み取りのみ。Steam起動中でもよい）。"""
        bases = [b.rstrip("/") for b in self._get_config().steam_deck.doujin_base]
        rows = self._db.list()
        by_appid = {r["steam_appid"]: r["id"] for r in rows if r["steam_appid"] is not None}
        by_exe = {
            normalize_path(f"{r['deck_dir']}/{r['exe']}"): r["id"]
            for r in rows if r["deck_dir"] and r["exe"] and r["steam_appid"] is None
        }
        with self._connect() as fs:
            user = self._resolve_user(self._users(fs))
            sc_path = self._shortcuts_path(user)
            if not fs.exists(sc_path):
                return SteamScan(shortcuts=[], suggested_bases=[])
            shortcuts = Shortcuts(fs.read_bytes(sc_path))
            cfg_path = f"{self._root()}/config/config.vdf"
            steam_cfg = text_vdf.loads(fs.read_text(cfg_path)) if fs.exists(cfg_path) else text_vdf.KV()
            grid_dir = posixpath.join(posixpath.dirname(sc_path), "grid")
            grid_files = set(fs.listdir(grid_dir)) if fs.exists(grid_dir) else set()

        result = []
        outside: list[str] = []
        for e in shortcuts.entries():
            appid = entry_appid(e)
            exe_path = normalize_path(str(e.get("Exe") or ""))
            if appid is None or not exe_path.lower().endswith(_WINDOWS_SUFFIXES):
                continue
            deck_dir, rel, in_base = _split_game_path(exe_path, bases)
            if not in_base:
                outside.append(exe_path)
            result.append(SteamShortcut(
                appid=appid, name=str(e.get("AppName") or ""), exe_path=exe_path,
                launch_options=str(e.get("LaunchOptions") or ""),
                compat_tool=get_compat_tool(steam_cfg, appid),
                has_art=any(_slot_files(grid_files, appid, st) for st in _GRID_STEMS.values()),
                deck_dir=deck_dir, exe=rel, in_base=in_base,
                linked_id=by_appid.get(appid),
                match_id=None if appid in by_appid else by_exe.get(exe_path),
            ))
        return SteamScan(shortcuts=result, suggested_bases=_suggest_bases(outside, bases))

    def import_shortcuts(self, appids: list[int]) -> list[DoujinGame]:
        """Steamに登録済みの非Steamゲームを台帳に取り込む。appID・Proton・起動オプションを引き継ぐ。

        同じ起動ファイルを指す未紐づけの作品が台帳にあれば、新規に作らずにそこへ紐づける。
        """
        wanted = set(appids)
        now = datetime.now()
        result = []
        for sc in self.scan_shortcuts().shortcuts:
            if sc.appid not in wanted or sc.linked_id is not None:
                continue
            steam_fields = {
                "steam_appid": sc.appid, "steam_registered_at": now,
                "compat_tool": sc.compat_tool, "launch_options": sc.launch_options,
            }
            if sc.match_id is not None:
                row = self._db.update(sc.match_id, steam_fields)
            else:
                guess = guess_from_folder_name(posixpath.basename(sc.deck_dir))
                row = self._db.create({
                    **guess.model_dump(), "title": sc.name or guess.title,
                    "deck_dir": sc.deck_dir, "exe": sc.exe, **steam_fields,
                })
            result.append(self._doujin.get(row["id"]))
        return result

    # ---- Steamに設定済みの画像を台帳へ取り込む ----

    def _locate(self, fs, game, shortcuts: Shortcuts | None) -> int | None:
        """台帳の作品に対応する Steam の appID（台帳に無ければ起動ファイルで探す）。"""
        if game.steam_appid:
            return game.steam_appid
        if shortcuts is not None and game.deck_dir and game.exe:
            entry = shortcuts.find_by_exe(f"{game.deck_dir.rstrip('/')}/{game.exe.lstrip('/')}")
            if entry is not None:
                return entry_appid(entry)
        return None

    def _grid_images(self, fs, game, appid: int, shortcuts: Shortcuts | None, grid_dir: str, grid_files: set[str]) -> list[GridImage]:
        result = []
        for steam_kind, stem in _GRID_STEMS.items():
            kind = _CATALOG_KIND[steam_kind]
            files = sorted(_slot_files(grid_files, appid, stem), key=_ext_preference)
            name = files[0] if files else ""
            if not name and steam_kind == "icon" and shortcuts is not None:
                # アイコンは shortcuts.vdf の icon 欄で grid の外のファイル（exe と同じ場所の .ico 等）を指すこともある
                entry = shortcuts.find(appid)
                icon = normalize_path(str(entry.get("icon") or "")) if entry is not None else ""
                if icon and posixpath.splitext(icon)[1].lower() in _GRID_EXTS and fs.exists(icon):
                    name = icon
            if name:
                result.append(GridImage(kind=kind, filename=name, in_catalog=kind in game.images))
        return result

    def _open_grid(self, fs):
        user = self._resolve_user(self._users(fs))
        sc_path = self._shortcuts_path(user)
        grid_dir = posixpath.join(posixpath.dirname(sc_path), "grid")
        shortcuts = Shortcuts(fs.read_bytes(sc_path)) if fs.exists(sc_path) else None
        grid_files = set(fs.listdir(grid_dir)) if fs.exists(grid_dir) else set()
        return shortcuts, grid_dir, grid_files

    def grid_images(self, game_id: int) -> list[GridImage]:
        """作品に Steam で設定されている画像の一覧（読み取りのみ。Steam起動中でもよい）。"""
        game = self._doujin.get(game_id)
        with self._connect() as fs:
            shortcuts, grid_dir, grid_files = self._open_grid(fs)
            appid = self._locate(fs, game, shortcuts)
            if appid is None:
                raise ValueError("Steamに登録されていない作品です。")
            return self._grid_images(fs, game, appid, shortcuts, grid_dir, grid_files)

    def grid_image_bytes(self, game_id: int, kind: str) -> tuple[bytes, str]:
        """Steam に設定されている画像の中身と拡張子。"""
        game = self._doujin.get(game_id)
        with self._connect() as fs:
            shortcuts, grid_dir, grid_files = self._open_grid(fs)
            appid = self._locate(fs, game, shortcuts)
            if appid is None:
                raise ValueError("Steamに登録されていない作品です。")
            img = next((g for g in self._grid_images(fs, game, appid, shortcuts, grid_dir, grid_files) if g.kind == kind), None)
            if img is None:
                raise NotFoundError(f"Steamに {kind} の画像は設定されていません。")
            path = img.filename if img.filename.startswith("/") else f"{grid_dir}/{img.filename}"
            return fs.read_bytes(path), posixpath.splitext(img.filename)[1].lower()

    def pull_art(
        self, ids: list[int], job: Job | None = None, kinds: list[str] | None = None, overwrite: bool = False,
    ) -> list[ArtPullResult]:
        """Steam に設定されている画像を台帳に取り込む。

        kinds を省略するとすべての種類が対象。overwrite=False なら台帳に既にある種類は取り込まない。
        """
        results = []
        with self._connect() as fs:
            shortcuts, grid_dir, grid_files = self._open_grid(fs)
            for i, game_id in enumerate(ids, 1):
                game = self._doujin.get(game_id)
                r = ArtPullResult(id=game.id, title=game.title)
                try:
                    appid = self._locate(fs, game, shortcuts)
                    if appid is None:
                        raise ValueError("Steamに登録されていない作品です。")
                    for img in self._grid_images(fs, game, appid, shortcuts, grid_dir, grid_files):
                        if kinds is not None and img.kind not in kinds:
                            continue
                        if img.in_catalog and not overwrite:
                            r.skipped.append(img.kind)
                            continue
                        path = img.filename if img.filename.startswith("/") else f"{grid_dir}/{img.filename}"
                        self._doujin.import_image_bytes(
                            game.id, img.kind, fs.read_bytes(path), posixpath.splitext(img.filename)[1],
                        )
                        r.imported.append(img.kind)
                    if job:
                        job.log(f"{game.title}: 取り込み {len(r.imported)}件" + (f"・台帳にあり {len(r.skipped)}件" if r.skipped else ""))
                except Exception as e:
                    r.error = str(e)
                    if job:
                        job.log(f"失敗: {game.title}: {e}")
                results.append(r)
                if job:
                    job.progress(i, len(ids))
        return results

    # ---- 画像 ----

    def art(self, game_id: int, kind: str) -> Image.Image | None:
        """Steamに送る画像を作る。kind は portrait/header/hero/logo/icon。"""
        game = self._doujin.get(game_id)
        sources = {k: Image.open(self._doujin.image_path(game_id, k)) for k in game.images}
        if kind in steam_art.ART_SPECS:
            return steam_art.build(kind, sources)
        if kind in ("logo", "icon"):
            img = sources.get(kind)
            return img.convert("RGBA") if img else None
        raise ValueError(f"不明な画像の種類です: {kind}")

    # ---- 登録・解除 ----

    def _shortcuts_path(self, user: SteamUser) -> str:
        return f"{self._root()}/userdata/{user.account_id}/config/shortcuts.vdf"

    def apply(self, ids: list[int], job: Job, overwrite_art: bool = False) -> list[SteamGameResult]:
        """台帳の作品を shortcuts.vdf に登録（登録済みなら更新）し、画像とProtonの設定も書き込む。

        overwrite_art=False のときは、Deckに既にあるライブラリ画像を残し、無い種類だけを書き込む。
        """
        return self._edit(ids, job, register=True, overwrite_art=overwrite_art)

    def remove(self, ids: list[int], job: Job) -> list[SteamGameResult]:
        """Steamから外す。appIDは台帳に残し、再登録したときにプレイ記録が引き継がれるようにする。"""
        return self._edit(ids, job, register=False)

    def _edit(self, ids: list[int], job: Job, register: bool, overwrite_art: bool = False) -> list[SteamGameResult]:
        config = self._get_config()
        results: list[SteamGameResult] = []
        with self._connect() as fs:
            if self._is_running(fs):
                raise SteamRunningError(
                    "DeckでSteamが起動しています。デスクトップモードに切り替え、Steamを終了してから実行してください"
                    "（起動中に書き込むと、Steamの終了時に上書きされて消えてしまいます）。"
                )
            user = self._resolve_user(self._users(fs))
            sc_path = self._shortcuts_path(user)
            grid_dir = posixpath.join(posixpath.dirname(sc_path), "grid")
            cfg_path = f"{self._root()}/config/config.vdf"

            shortcuts = Shortcuts(fs.read_bytes(sc_path) if fs.exists(sc_path) else None)
            steam_cfg = text_vdf.loads(fs.read_text(cfg_path)) if fs.exists(cfg_path) else text_vdf.KV()
            cfg_before = text_vdf.dumps(steam_cfg)
            grid_files = set(fs.listdir(grid_dir)) if fs.exists(grid_dir) else set()
            job.log(f"Steamアカウント: {user.persona_name or user.account_id}")

            done: list[tuple[int, int | None]] = []
            claimed: dict[int, str] = {}  # この処理で使ったappID → 作品名
            for i, game_id in enumerate(ids, 1):
                game = self._doujin.get(game_id)
                result = SteamGameResult(id=game.id, title=game.title)
                try:
                    if register:
                        result.appid, result.action = self._register_one(
                            fs, game, shortcuts, steam_cfg, grid_dir, grid_files, config, overwrite_art, claimed,
                        )
                        claimed[result.appid] = game.title
                    else:
                        result.appid, result.action = self._remove_one(fs, game, shortcuts, steam_cfg, grid_dir, grid_files)
                    done.append((game.id, result.appid))
                    job.log(f"{result.action}: {game.title}")
                except Exception as e:
                    result.error = str(e)
                    job.log(f"失敗: {game.title}: {e}")
                results.append(result)
                job.progress(i, len(ids))

            if done:
                write_with_backup(fs, sc_path, shortcuts.dumps(), config.backup_max)
                new_cfg = text_vdf.dumps(steam_cfg)
                if new_cfg != cfg_before:
                    write_with_backup(fs, cfg_path, new_cfg, config.backup_max)

        now = datetime.now()
        for game_id, appid in done:
            if register:
                self._db.update(game_id, {"steam_appid": appid, "steam_registered_at": now})
            else:
                self._db.update(game_id, {"steam_registered_at": None})
        if done:
            job.log("完了しました。Steamを起動すると反映されます。")
        return results

    def _register_one(
        self, fs, game, shortcuts: Shortcuts, steam_cfg, grid_dir: str, grid_files: set[str],
        config: Config, overwrite_art: bool, claimed: dict[int, str],
    ):
        if not game.deck_dir:
            raise ValueError("Deckに転送されていません（Deck上の作品フォルダが未設定）。")
        if not game.exe:
            raise ValueError("起動ファイルが設定されていません。")
        exe_path = f"{game.deck_dir.rstrip('/')}/{game.exe.lstrip('/')}"
        exe = quote(exe_path)
        name = game.title or posixpath.basename(game.deck_dir)

        # 既存のエントリを探す: 台帳のappID → 同じ起動ファイルを指すエントリ（手動などで登録済みのもの）
        existing = shortcuts.find(game.steam_appid) if game.steam_appid else None
        if existing is None:
            existing = shortcuts.find_by_exe(exe_path)
        appid = (entry_appid(existing) if existing is not None else None) or game.steam_appid or shortcut_appid(exe, name)
        owner = next((r["title"] for r in self._db.list() if r["steam_appid"] == appid and r["id"] != game.id), None)
        owner = owner or claimed.get(appid)
        if owner is not None:
            raise ValueError(f"このSteamの登録（appID {appid}）は、台帳の「{owner}」が使っています。")

        # 既存のエントリでは、台帳で明示的に指定した項目だけを変え、それ以外はSteam側の設定を残す
        written = self._write_art(fs, game.id, appid, grid_dir, grid_files, overwrite_art or existing is None)
        if game.launch_options:
            launch: str | None = game.launch_options
        else:
            launch = None if existing is not None else config.steam_deck.default_launch_options
        created = shortcuts.upsert(ShortcutSpec(
            appid=appid, name=name, exe=exe, start_dir=quote(posixpath.dirname(exe_path)),
            icon=f"{grid_dir}/{appid}{_GRID_STEMS['icon']}.png" if "icon" in written else (None if existing is not None else ""),
            launch_options=launch,
        ))
        needs_proton = exe_path.lower().endswith(_WINDOWS_SUFFIXES)
        if not needs_proton:
            set_compat_tool(steam_cfg, appid, "")
        elif game.compat_tool:
            set_compat_tool(steam_cfg, appid, game.compat_tool)
        elif existing is None or not get_compat_tool(steam_cfg, appid):
            set_compat_tool(steam_cfg, appid, config.steam_deck.default_compat_tool)
        if created:
            return appid, "登録"
        return appid, "更新" if game.steam_appid == appid else "既存の登録を引き継いで更新"

    def _remove_one(self, fs, game, shortcuts: Shortcuts, steam_cfg, grid_dir: str, grid_files: set[str]):
        appid = game.steam_appid
        if appid is None:
            raise ValueError("Steamに登録されていません。")
        shortcuts.remove(appid)
        if get_compat_tool(steam_cfg, appid):
            set_compat_tool(steam_cfg, appid, "")
        for stem in _GRID_STEMS.values():
            for f in _slot_files(grid_files, appid, stem):
                fs.remove(f"{grid_dir}/{f}")
                grid_files.discard(f)
        return appid, "解除"

    def _write_art(
        self, fs, game_id: int, appid: int, grid_dir: str, grid_files: set[str], overwrite: bool,
    ) -> set[str]:
        """グリッド画像を書き込み、書いた種類を返す。

        台帳から作れない種類には触れない（利用者が自分で付けた画像を消さない）。
        overwrite=False のときは、Deckに既に画像がある種類も触れない。
        """
        written = set()
        for kind, stem in _GRID_STEMS.items():
            existing = _slot_files(grid_files, appid, stem)
            if existing and not overwrite:
                continue
            img = self.art(game_id, kind)
            if img is None:
                continue
            name = f"{appid}{stem}.png"
            fs.write_bytes(f"{grid_dir}/{name}", art_png(img))
            # 拡張子違いの古い画像が残っていると、Steamがどちらを使うか定まらないので消す
            for old in existing:
                if old != name:
                    fs.remove(f"{grid_dir}/{old}")
                    grid_files.discard(old)
            grid_files.add(name)
            written.add(kind)
        return written


_TOO_SHALLOW = {"/", "/home", "/home/deck", "/run", "/run/media", "/run/media/deck"}


def _suggest_bases(exe_paths: list[str], bases: list[str]) -> list[str]:
    """格納先の外にある起動ファイルから、格納先に向いていそうなフォルダを推定する。

    2つ以上の異なる子フォルダに作品があるフォルダを候補にし、候補の中に別の候補を含むもの
    （/home/deck/Documents など上位すぎるもの）は除く。
    """
    children: dict[str, set[str]] = {}
    for exe in exe_paths:
        parts = exe.split("/")[1:-1]  # 先頭の空文字と、ファイル名を除く
        for i in range(1, len(parts)):
            anc = "/" + "/".join(parts[:i])
            children.setdefault(anc, set()).add(parts[i])
    cands = {
        a for a, kids in children.items()
        if len(kids) >= 2 and a not in _TOO_SHALLOW and not any(b == a or b.startswith(a + "/") for b in bases)
    }
    return sorted(a for a in cands if not any(o != a and o.startswith(a + "/") for o in cands))


def _split_game_path(exe_path: str, bases: list[str]) -> tuple[str, str, bool]:
    """起動ファイルのパスを (作品フォルダ, 相対パス, 格納先の中か) に分ける。

    格納先の中なら、格納先の直下のフォルダを作品フォルダとする（"作品/maid/Game.exe" のような深い配置に対応）。
    格納先の外なら、起動ファイルのあるフォルダを作品フォルダとする。
    """
    for base in sorted(bases, key=len, reverse=True):
        if exe_path.startswith(base + "/"):
            rest = exe_path[len(base) + 1:]
            if "/" in rest:
                top, rel = rest.split("/", 1)
                return f"{base}/{top}", rel, True
    return posixpath.dirname(exe_path), posixpath.basename(exe_path), False


# Steam のグリッド画像の種類 → 台帳の画像の種類
_CATALOG_KIND = {"portrait": "cover", "header": "header", "hero": "hero", "logo": "logo", "icon": "icon"}


def _ext_preference(filename: str) -> int:
    """同じ種類の画像が複数の拡張子であるとき、どれを使うか（PNG を優先）。"""
    order = [".png", ".jpg", ".jpeg", ".webp", ".ico"]
    ext = posixpath.splitext(filename)[1].lower()
    return order.index(ext) if ext in order else len(order)


def _slot_files(grid_files: set[str], appid: int, stem: str) -> list[str]:
    """指定した種類（stem）のグリッド画像のファイル名。拡張子は問わない。"""
    return sorted(f for f in grid_files if f"{appid}{stem}" == posixpath.splitext(f)[0] and posixpath.splitext(f)[1].lower() in _GRID_EXTS)


def art_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
