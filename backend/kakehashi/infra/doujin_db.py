"""同人ゲーム台帳（SQLite）。"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from kakehashi.errors import NotFoundError

# user_version ごとのマイグレーション。スキーマを変えるときは末尾に追加する。
_MIGRATIONS = [
    """
    CREATE TABLE doujin_games (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL DEFAULT '',
        circle TEXT NOT NULL DEFAULT '',
        work_id TEXT NOT NULL DEFAULT '',
        store TEXT NOT NULL DEFAULT '',
        url TEXT NOT NULL DEFAULT '',
        tags TEXT NOT NULL DEFAULT '[]',
        description TEXT NOT NULL DEFAULT '',
        release_date TEXT NOT NULL DEFAULT '',
        play_status TEXT NOT NULL DEFAULT 'unplayed',
        rating INTEGER,
        notes TEXT NOT NULL DEFAULT '',
        local_path TEXT NOT NULL DEFAULT '',
        exe TEXT NOT NULL DEFAULT '',
        deck_dir TEXT NOT NULL DEFAULT '',
        transferred_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX idx_doujin_work_id ON doujin_games(work_id);
    """,
]

_COLUMNS = (
    "title", "circle", "work_id", "store", "url", "tags", "description", "release_date",
    "play_status", "rating", "notes", "local_path", "exe", "deck_dir", "transferred_at",
)


class DoujinDB:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._migrate()

    def _migrate(self) -> None:
        with self._lock, self._conn:
            version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            for i, sql in enumerate(_MIGRATIONS[version:], start=version + 1):
                self._conn.executescript(sql)
                self._conn.execute(f"PRAGMA user_version = {i}")

    def list(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM doujin_games ORDER BY id").fetchall()
        return [_to_dict(r) for r in rows]

    def get(self, game_id: int) -> dict:
        with self._lock:
            row = self._conn.execute("SELECT * FROM doujin_games WHERE id = ?", (game_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"同人ゲームが見つかりません（id={game_id}）")
        return _to_dict(row)

    def create(self, fields: dict) -> dict:
        now = datetime.now().isoformat(timespec="seconds")
        data = _encode({k: v for k, v in fields.items() if k in _COLUMNS})
        cols = [*data, "created_at", "updated_at"]
        with self._lock, self._conn:
            cur = self._conn.execute(
                f"INSERT INTO doujin_games ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                [*data.values(), now, now],
            )
            new_id = cur.lastrowid
        return self.get(new_id)

    def update(self, game_id: int, fields: dict) -> dict:
        data = _encode({k: v for k, v in fields.items() if k in _COLUMNS})
        if data:
            data["updated_at"] = datetime.now().isoformat(timespec="seconds")
            with self._lock, self._conn:
                cur = self._conn.execute(
                    f"UPDATE doujin_games SET {', '.join(f'{k} = ?' for k in data)} WHERE id = ?",
                    [*data.values(), game_id],
                )
            if cur.rowcount == 0:
                raise NotFoundError(f"同人ゲームが見つかりません（id={game_id}）")
        return self.get(game_id)

    def delete(self, game_id: int) -> None:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM doujin_games WHERE id = ?", (game_id,))
        if cur.rowcount == 0:
            raise NotFoundError(f"同人ゲームが見つかりません（id={game_id}）")

    def close(self) -> None:
        self._conn.close()


def _encode(data: dict) -> dict:
    out = dict(data)
    if "tags" in out:
        out["tags"] = json.dumps(out["tags"] or [], ensure_ascii=False)
    if isinstance(out.get("transferred_at"), datetime):
        out["transferred_at"] = out["transferred_at"].isoformat(timespec="seconds")
    return out


def _to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["tags"] = json.loads(d["tags"] or "[]")
    return d
