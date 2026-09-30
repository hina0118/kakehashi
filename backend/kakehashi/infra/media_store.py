"""PC側のメディアフォルダ（downloaded_media/{機種}/{フォルダ}/{ROM名}.{拡張子}）の読み書き。

ROM名には "[" などglobの特殊文字が含まれることがあるため、globは使わずに
ファイル名の stem を完全一致で比較する。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from kakehashi.domain.media import MEDIA_FOLDERS


def list_folder(folder_dir: Path) -> list[Path]:
    if not folder_dir.is_dir():
        return []
    return sorted(p for p in folder_dir.iterdir() if p.is_file() and not p.name.endswith(".part"))


def find_files(base: Path, folder: str, stem: str) -> list[Path]:
    return [p for p in list_folder(base / folder) if p.stem == stem]


def scan(base: Path) -> dict[str, dict[str, str]]:
    """stem → {フォルダ: ファイル名}。1フォルダ1回の走査で全ゲーム分をまとめて返す。"""
    result: dict[str, dict[str, str]] = {}
    for folder in MEDIA_FOLDERS:
        for p in list_folder(base / folder):
            result.setdefault(p.stem, {}).setdefault(folder, p.name)
    return result


class PendingDeletions:
    """PCで削除・差し替えたが、まだDeckから消していないメディアファイルの記録。

    Deckから取得する際にこれらを除外し、次のプッシュでDeckからも削除する。
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def _load(self) -> dict[str, list[str]]:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}

    def _save(self, data: dict[str, list[str]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, system: str) -> set[str]:
        """"{フォルダ}/{ファイル名}" の集合。"""
        with self._lock:
            return set(self._load().get(system, []))

    def add(self, system: str, rel: str) -> None:
        self._update(system, add={rel})

    def discard(self, system: str, rels: set[str]) -> None:
        self._update(system, remove=rels)

    def _update(self, system: str, add: set[str] = frozenset(), remove: set[str] = frozenset()) -> None:
        with self._lock:
            data = self._load()
            items = (set(data.get(system, [])) | add) - remove
            if items:
                data[system] = sorted(items)
            else:
                data.pop(system, None)
            self._save(data)
