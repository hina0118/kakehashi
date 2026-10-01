from __future__ import annotations

import posixpath
from contextlib import contextmanager
from pathlib import Path

import pytest

from kakehashi.config import Config, DeckPaths, LocalPaths, SyncSettings
from kakehashi.context import AppContext
from kakehashi.infra.deck import TransferResult


class MemoryFS:
    """RemoteFS のインメモリ実装。ディレクトリはファイルパスから暗黙に存在するものとする。"""

    def __init__(self, files: dict[str, str | bytes] | None = None) -> None:
        self.files: dict[str, str | bytes] = dict(files or {})
        self.connections = 0
        self.steam_running = False
        self.commands: list[str] = []
        self.mtimes: dict[str, int] = {}
        self._clock = 1000

    def read_text(self, path: str) -> str:
        data = self.read_bytes(path)
        return data.decode("utf-8")

    def write_text(self, path: str, content: str) -> None:
        self.files[path] = content
        self.touch(path)

    def touch(self, path: str) -> None:
        """更新日時を進める（Steam側でファイルが変わったことを表すのにも使う）。"""
        self._clock += 1
        self.mtimes[path] = self._clock

    def list_attrs(self, path: str) -> dict[str, tuple[int, int]]:
        return {
            name: (size, self.mtimes.get(f"{path.rstrip('/')}/{name}", 0))
            for name, size in self.list_files(path).items()
        }

    def read_bytes(self, path: str) -> bytes:
        if path not in self.files:
            raise FileNotFoundError(path)
        c = self.files[path]
        return c.encode("utf-8") if isinstance(c, str) else c

    def write_bytes(self, path: str, content: bytes) -> None:
        self.files[path] = content
        self.touch(path)

    def run(self, command: str, timeout: float = 30) -> tuple[int, str, str]:
        self.commands.append(command)
        if "pgrep" in command:
            return 0, ("running" if self.steam_running else "stopped") + "\n", ""
        return 0, "", ""

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

    def list_files(self, path: str) -> dict[str, int]:
        prefix = path.rstrip("/") + "/"
        return {
            p[len(prefix):]: len(c.encode("utf-8") if isinstance(c, str) else c)
            for p, c in self.files.items() if p.startswith(prefix) and "/" not in p[len(prefix):]
        }

    def list_dirs(self, path: str) -> list[str]:
        prefix = path.rstrip("/") + "/"
        return sorted({p[len(prefix):].split("/", 1)[0] for p in self.files if p.startswith(prefix) and "/" in p[len(prefix):]})

    def walk_files(self, path: str):
        prefix = path.rstrip("/") + "/"
        return iter(sorted(p for p in self.files if p.startswith(prefix)))

    def upload(self, tasks, overwrite=False, on_progress=None) -> TransferResult:
        res = TransferResult()
        for i, (local, remote) in enumerate(tasks, 1):
            data = Path(local).read_text(encoding="utf-8")
            if not overwrite and remote in self.files and len(self.files[remote].encode()) == len(data.encode()):
                res.skipped += 1
            else:
                self.files[remote] = data
                res.transferred += 1
            if on_progress:
                on_progress(i, len(tasks))
        return res

    def download(self, tasks, on_progress=None) -> TransferResult:
        res = TransferResult()
        for i, (remote, local) in enumerate(tasks, 1):
            Path(local).parent.mkdir(parents=True, exist_ok=True)
            Path(local).write_text(self.files[remote], encoding="utf-8")
            res.transferred += 1
            if on_progress:
                on_progress(i, len(tasks))
        return res

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
    monkeypatch.setenv("KAKEHASHI_DATA_DIR", str(tmp_path / "data"))
    config = Config(
        systems=["ps2"], backup_max=2,
        windows=LocalPaths(media_base=str(tmp_path / "media")),
        steam_deck=DeckPaths(gamelist_base="/deck/gamelists", rom_base="/deck/roms", media_base="/deck/media"),
        sync=SyncSettings(host="deck.test", password="secret"),
    )
    c = AppContext(config)
    c.connect = deck_fs.connect  # type: ignore[method-assign]
    return c


def backups(fs: MemoryFS) -> list[str]:
    return sorted(p for p in fs.files if p.endswith(".bak") and posixpath.dirname(p) == posixpath.dirname(GAMELIST_PATH))
