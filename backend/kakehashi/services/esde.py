"""ES-DEのゲーム（Deck上のgamelist.xml）の参照・編集。"""
from __future__ import annotations

import re
import threading
from pathlib import Path, PurePosixPath
from typing import Callable

from kakehashi.config import Config
from kakehashi.domain.esde import EDITABLE_FIELDS, EsdeGame, GameUpdate, UpdateResult
from kakehashi.infra.deck import DeckConnector, RemoteFS, write_with_backup
from kakehashi.infra.gamelist import Gamelist
from kakehashi.services.jobs import Job

_EXTENSIONS_RE = re.compile(r"\s*extensions\s*:\s*(.+)", re.IGNORECASE)


class EsdeService:
    def __init__(self, get_config: Callable[[], Config], connect: DeckConnector) -> None:
        self._get_config = get_config
        self._connect = connect
        self._cache: dict[str, list[EsdeGame]] = {}
        self._lock = threading.Lock()

    def list_systems(self) -> list[str]:
        return list(self._get_config().systems)

    def get_games(self, system: str, refresh: bool = False) -> list[EsdeGame]:
        """gamelist.xmlのゲーム一覧。refresh=Falseなら前回取得分を返す。"""
        if refresh or system not in self._cache:
            with self._connect() as fs:
                self._cache[system] = self._read(fs, system).to_models()
        return self._cache[system]

    def find_unregistered_roms(self, system: str) -> list[EsdeGame]:
        """DeckのROMフォルダにあってgamelist.xmlに未登録のファイルを返す。

        ROMフォルダ直下のmetadata.txtに "extensions:" 行があればその拡張子で絞り込む。
        """
        known = {PurePosixPath(g.path).name for g in self.get_games(system)}
        rom_dir = self._get_config().steam_deck.rom_dir(system)
        with self._connect() as fs:
            try:
                entries = fs.listdir(rom_dir)
            except FileNotFoundError:
                return []
            extensions = _read_rom_extensions(fs, rom_dir)
        names = [
            n for n in sorted(entries)
            if not n.startswith(".") and n != "metadata.txt" and n not in known
            and (not extensions or PurePosixPath(n).suffix.lower() in extensions)
        ]
        return [EsdeGame(path=f"./{n}", registered=False) for n in names]

    def upload_roms(self, system: str, files: list[Path], job: Job, overwrite: bool = False) -> dict:
        """PCのROMファイルをDeckのROMフォルダへ送る。送ったROMは未登録ROMとして一覧に現れる。"""
        missing = [str(f) for f in files if not f.is_file()]
        if missing:
            raise ValueError(f"ファイルが見つかりません: {', '.join(missing)}")
        rom_dir = self._get_config().steam_deck.rom_dir(system)
        job.log(f"送信先: {rom_dir}/")
        with self._connect() as fs:
            res = fs.upload([(f, f"{rom_dir}/{f.name}") for f in files], overwrite=overwrite, on_progress=job.progress)
        for e in res.errors:
            job.log(f"失敗: {e}")
        return {"transferred": res.transferred, "skipped": res.skipped, "errors": res.errors}

    def update_games(
        self, system: str, updates: list[GameUpdate], deleted: list[str] | None = None,
    ) -> UpdateResult:
        """最新のgamelist.xmlを取得して差分だけをマージし、バックアップを取ってから書き戻す。"""
        diffs: dict[str, dict[str, str]] = {}
        for u in updates:
            unknown = set(u.fields) - set(EDITABLE_FIELDS)
            if unknown:
                raise ValueError(f"編集できないフィールドです（{u.path}）: {sorted(unknown)}")
            diffs.setdefault(u.path, {}).update(u.fields)
        deleted_set = set(deleted or [])
        if not diffs and not deleted_set:
            return UpdateResult(applied=0, requested=0)

        config = self._get_config()
        with self._lock, self._connect() as fs:
            gamelist = self._read(fs, system)
            applied, deleted_count = gamelist.apply(diffs, deleted_set)
            write_with_backup(fs, config.steam_deck.gamelist_path(system), gamelist.serialize(), config.backup_max)
            self._cache[system] = gamelist.to_models()
        return UpdateResult(applied=applied, deleted=deleted_count, requested=len(diffs) + len(deleted_set))

    def _read(self, fs: RemoteFS, system: str) -> Gamelist:
        path = self._get_config().steam_deck.gamelist_path(system)
        if not fs.exists(path):
            return Gamelist('<?xml version="1.0"?>\n<gameList />')
        return Gamelist(fs.read_text(path))


def _read_rom_extensions(fs: RemoteFS, rom_dir: str) -> set[str]:
    try:
        content = fs.read_text(f"{rom_dir}/metadata.txt")
    except FileNotFoundError:
        return set()
    for line in content.splitlines():
        if m := _EXTENSIONS_RE.match(line):
            tokens = re.split(r"[,\s]+", m.group(1).strip())
            return {(t if t.startswith(".") else f".{t}").lower() for t in tokens if t}
    return set()
