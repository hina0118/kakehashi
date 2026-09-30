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
from kakehashi.imaging import steam_art
from kakehashi.infra.deck import DeckConnector, TransferFS, write_with_backup
from kakehashi.infra.doujin_db import DoujinDB
from kakehashi.infra.steam import text_vdf
from kakehashi.infra.steam.config import SteamUser, get_compat_tool, parse_login_users, set_compat_tool
from kakehashi.infra.steam.shortcuts import ShortcutSpec, Shortcuts, quote, shortcut_appid
from kakehashi.services.doujin import DoujinService
from kakehashi.services.jobs import Job

# Steam のグリッド画像のファイル名（{appid} に続く部分）
_GRID_FILES = {"portrait": "p.png", "header": ".png", "hero": "_hero.png", "logo": "_logo.png", "icon": "_icon.png"}
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

    def apply(self, ids: list[int], job: Job) -> list[SteamGameResult]:
        """台帳の作品を shortcuts.vdf に登録（登録済みなら更新）し、画像とProtonの設定も書き込む。"""
        return self._edit(ids, job, register=True)

    def remove(self, ids: list[int], job: Job) -> list[SteamGameResult]:
        """Steamから外す。appIDは台帳に残し、再登録したときにプレイ記録が引き継がれるようにする。"""
        return self._edit(ids, job, register=False)

    def _edit(self, ids: list[int], job: Job, register: bool) -> list[SteamGameResult]:
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
            job.log(f"Steamアカウント: {user.persona_name or user.account_id}")

            done: list[tuple[int, int | None]] = []
            for i, game_id in enumerate(ids, 1):
                game = self._doujin.get(game_id)
                result = SteamGameResult(id=game.id, title=game.title)
                try:
                    if register:
                        result.appid, result.action = self._register_one(fs, game, shortcuts, steam_cfg, grid_dir, config)
                    else:
                        result.appid, result.action = self._remove_one(fs, game, shortcuts, steam_cfg, grid_dir)
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

    def _register_one(self, fs, game, shortcuts: Shortcuts, steam_cfg, grid_dir: str, config: Config):
        if not game.deck_dir:
            raise ValueError("Deckに転送されていません（Deck上の作品フォルダが未設定）。")
        if not game.exe:
            raise ValueError("起動ファイルが設定されていません。")
        exe_path = f"{game.deck_dir.rstrip('/')}/{game.exe.lstrip('/')}"
        exe = quote(exe_path)
        name = game.title or posixpath.basename(game.deck_dir)
        appid = game.steam_appid or shortcut_appid(exe, name)

        written = self._write_art(fs, game.id, appid, grid_dir)
        created = shortcuts.upsert(ShortcutSpec(
            appid=appid, name=name, exe=exe, start_dir=quote(posixpath.dirname(exe_path)),
            icon=f"{grid_dir}/{appid}{_GRID_FILES['icon']}" if "icon" in written else "",
            launch_options=game.launch_options or config.steam_deck.default_launch_options,
        ))
        tool = game.compat_tool or config.steam_deck.default_compat_tool
        needs_proton = exe_path.lower().endswith(_WINDOWS_SUFFIXES)
        set_compat_tool(steam_cfg, appid, tool if needs_proton else "")
        return appid, "登録" if created else "更新"

    def _remove_one(self, fs, game, shortcuts: Shortcuts, steam_cfg, grid_dir: str):
        appid = game.steam_appid
        if appid is None:
            raise ValueError("Steamに登録されていません。")
        shortcuts.remove(appid)
        if get_compat_tool(steam_cfg, appid):
            set_compat_tool(steam_cfg, appid, "")
        for suffix in _GRID_FILES.values():
            path = f"{grid_dir}/{appid}{suffix}"
            if fs.exists(path):
                fs.remove(path)
        return appid, "解除"

    def _write_art(self, fs, game_id: int, appid: int, grid_dir: str) -> set[str]:
        """グリッド画像を書き込み、書いた種類を返す。台帳から消した画像はDeckからも消す。"""
        written = set()
        for kind, suffix in _GRID_FILES.items():
            path = f"{grid_dir}/{appid}{suffix}"
            img = self.art(game_id, kind)
            if img is None:
                if fs.exists(path):
                    fs.remove(path)
                continue
            fs.write_bytes(path, art_png(img))
            written.add(kind)
        return written


def art_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
