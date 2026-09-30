from __future__ import annotations

import posixpath
from contextlib import contextmanager

import pytest

from kakehashi.config import Config, DeckPaths, SyncSettings
from kakehashi.context import AppContext


class MemoryFS:
    """RemoteFS のインメモリ実装。ディレクトリはファイルパスから暗黙に存在するものとする。"""

    def __init__(self, files: dict[str, str] | None = None) -> None:
        self.files: dict[str, str] = dict(files or {})
        self.connections = 0

    def read_text(self, path: str) -> str:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def write_text(self, path: str, content: str) -> None:
        self.files[path] = content

    def listdir(self, path: str) -> list[str]:
        prefix = path.rstrip("/") + "/"
        names = {p[len(prefix):].split("/", 1)[0] for p in self.files if p.startswith(prefix)}
        if not names:
            raise FileNotFoundError(path)
        return sorted(names)

    def exists(self, path: str) -> bool:
        prefix = path.rstrip("/") + "/"
        return path in self.files or any(p.startswith(prefix) for p in self.files)

    def remove(self, path: str) -> None:
        del self.files[path]

    @contextmanager
    def connect(self):
        self.connections += 1
        yield self


GAMELIST_PATH = "/deck/gamelists/ps2/gamelist.xml"

SAMPLE_GAMELIST = """<?xml version="1.0"?>
<alternativeEmulator>
\t<label>PCSX2</label>
</alternativeEmulator>
<gameList>
\t<game>
\t\t<path>./a.chd</path>
\t\t<name>Game A</name>
\t\t<favorite>true</favorite>
\t</game>
\t<game>
\t\t<path>./b.chd</path>
\t\t<name>Game B</name>
\t\t<desc>old</desc>
\t</game>
</gameList>
"""


@pytest.fixture
def deck_fs() -> MemoryFS:
    return MemoryFS({
        GAMELIST_PATH: SAMPLE_GAMELIST,
        "/deck/roms/ps2/a.chd": "",
        "/deck/roms/ps2/b.chd": "",
        "/deck/roms/ps2/c.chd": "",
        "/deck/roms/ps2/c.txt": "",
        "/deck/roms/ps2/metadata.txt": "system: ps2\nextensions: .chd .iso\n",
    })


@pytest.fixture
def ctx(deck_fs: MemoryFS, tmp_path, monkeypatch) -> AppContext:
    monkeypatch.setenv("KAKEHASHI_CONFIG_PATH", str(tmp_path / "config.json"))
    config = Config(
        systems=["ps2"], backup_max=2,
        steam_deck=DeckPaths(gamelist_base="/deck/gamelists", rom_base="/deck/roms"),
        sync=SyncSettings(host="deck.test", password="secret"),
    )
    c = AppContext(config)
    c.connect = deck_fs.connect  # type: ignore[method-assign]
    return c


def backups(fs: MemoryFS) -> list[str]:
    return sorted(p for p in fs.files if p.endswith(".bak") and posixpath.dirname(p) == posixpath.dirname(GAMELIST_PATH))
