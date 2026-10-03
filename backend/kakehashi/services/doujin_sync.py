"""同人ゲームの作品フォルダを、Deckを正としてPCと同期し、更新データを適用する。

流れ: Deckから取得 → 更新データ（展開済みのフォルダ）を重ねる → Deckへ反映

取得・反映のたびに、Deck上のファイルの状態（サイズ・更新日時）を「前回同期した状態」として記録する。
反映するときは PC・Deck・前回の記録の3つを比べ、PCだけが変わったファイルを送る。
Deckだけが変わったファイル（Deckで遊んでセーブが増えた等）は送らず、両方で変わったものは知らせる。
取得・反映ではどちらのファイルも削除しない（新しいバージョンで無くなったファイルやセーブデータを消さない）。
"""
from __future__ import annotations

import filecmp
import json
import os
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable

from pydantic import BaseModel

from kakehashi.config import Config
from kakehashi.errors import NotFoundError
from kakehashi.infra.deck import DeckConnector
from kakehashi.infra.doujin_db import DoujinDB
from kakehashi.services.jobs import Job

Attrs = tuple[int, int]
"""(サイズ, 更新日時[秒])"""

_VERSION = re.compile(r"(?<![A-Za-z])(?:ver|v)\.?\s*(\d+(?:[._]\d+)*[a-z]?)", re.IGNORECASE)
_LIST_LIMIT = 300


class PullResult(BaseModel):
    local_dir: str
    downloaded: int
    unchanged: int
    kept_local: list[str] = []
    """PCで変更してまだ反映していないため、取得しなかったファイル"""
    local_only: int = 0
    """PCにだけあるファイルの数（削除はしない）"""
    errors: list[str] = []


class SyncStatus(BaseModel):
    synced_before: bool
    """前回同期した記録があるか"""
    local_dir: str
    local_changed: list[str] = []
    """PCで変わった（Deckへ送る）ファイル"""
    remote_changed: list[str] = []
    """Deckで変わった（取得すると更新される）ファイル"""
    conflicts: list[str] = []
    """PCとDeckの両方で変わったファイル"""


class UpdateFile(BaseModel):
    path: str
    status: str
    """new（追加）/ changed（変更）"""
    size: int


class UpdatePlan(BaseModel):
    source: str
    root: str
    """更新データの中で、作品フォルダに当たるフォルダ（source からの相対パス。直下なら空）"""
    root_candidates: list[str]
    """選び直せる位置"""
    exe_found: bool
    """更新データの中に、台帳の起動ファイルと同じ位置のファイルがあったか"""
    version: str
    """フォルダ名から推定したバージョン"""
    new: int
    changed: int
    same: int
    files: list[UpdateFile]
    """追加・変更されるファイル（多いときは先頭の一部）"""


class ApplyResult(BaseModel):
    copied: int
    version: str
    exe_exists: bool


class PushResult(BaseModel):
    deck_dir: str
    pushed: int
    unchanged: int
    kept_remote: list[str] = []
    """Deckでだけ変わったため送らなかったファイル"""
    conflicts: list[str] = []
    """両方で変わったため送らなかったファイル（force=True なら送る）"""
    errors: list[str] = []


class SnapshotStore:
    """作品ごとの「前回同期したときのDeck上のファイルの状態」。"""

    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._lock = threading.Lock()

    def _path(self, game_id: int) -> Path:
        return self._dir / f"{game_id}.json"

    def get(self, game_id: int) -> dict[str, Attrs] | None:
        try:
            data = json.loads(self._path(game_id).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        return {k: (v[0], v[1]) for k, v in data.items()}

    def save(self, game_id: int, snap: dict[str, Attrs]) -> None:
        with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            tmp = self._path(game_id).with_suffix(".tmp")
            tmp.write_text(json.dumps({k: list(v) for k, v in sorted(snap.items())}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._path(game_id))

    def delete(self, game_id: int) -> None:
        self._path(game_id).unlink(missing_ok=True)


class DoujinSyncService:
    def __init__(
        self, get_config: Callable[[], Config], connect: DeckConnector, db: DoujinDB, snapshots: SnapshotStore,
    ) -> None:
        self._get_config = get_config
        self._connect = connect
        self._db = db
        self._snapshots = snapshots

    # ---- 場所 ----

    def _local_dir(self, game: dict) -> Path:
        if game["local_path"]:
            return Path(game["local_path"])
        base = self._get_config().windows.doujin_base
        if not base:
            raise ValueError("設定画面で、PC側の同人ゲームフォルダを指定してください。")
        if not game["deck_dir"]:
            raise ValueError("PC側の作品フォルダが設定されていません。")
        return Path(base) / PurePosixPath(game["deck_dir"]).name

    # ---- Deckから取得 ----

    def pull(self, game_id: int, job: Job | None = None, force: bool = False) -> PullResult:
        """Deck上の作品フォルダをPCへ取得する。変わったファイルだけを取り、PCのファイルは削除しない。

        PCで変更してまだDeckへ反映していないファイルは、force=True でなければ上書きしない。
        """
        game = self._db.get(game_id)
        if not game["deck_dir"]:
            raise ValueError("Deck上の作品フォルダが設定されていません。")
        local_dir = self._local_dir(game)
        snap = self._snapshots.get(game_id) or {}
        local = _local_attrs(local_dir)

        with self._connect() as fs:
            remote = fs.walk_attrs(game["deck_dir"])
            if not remote:
                raise NotFoundError(f"Deck上に作品フォルダが見つからないか、空です: {game['deck_dir']}")
            tasks, kept, unchanged = [], [], 0
            for rel, attrs in sorted(remote.items()):
                cur = local.get(rel)
                if cur == attrs:
                    unchanged += 1
                    continue
                if cur is not None and rel in snap and cur != snap[rel] and not force:
                    kept.append(rel)  # PCで変更済み（未反映）
                    continue
                tasks.append((f"{game['deck_dir'].rstrip('/')}/{rel}", local_dir / rel))
            if job:
                job.log(f"取得先: {local_dir}（{len(tasks)}ファイルを取得）")
            res = fs.download(tasks, on_progress=job.progress if job else None)

        failed = {e.split(":", 1)[0] for e in res.errors}
        new_snap = dict(snap)
        for rel, attrs in remote.items():
            if rel not in kept and PurePosixPath(rel).name not in failed:
                new_snap[rel] = attrs
        self._snapshots.save(game_id, new_snap)
        if not game["local_path"]:
            self._db.update(game_id, {"local_path": str(local_dir)})
        return PullResult(
            local_dir=str(local_dir), downloaded=res.transferred, unchanged=unchanged, kept_local=kept,
            local_only=len(set(local) - set(remote)), errors=res.errors,
        )

    # ---- 状態 ----

    def status(self, game_id: int) -> SyncStatus:
        game = self._db.get(game_id)
        local_dir = self._local_dir(game)
        snap = self._snapshots.get(game_id)
        local = _local_attrs(local_dir)
        remote: dict[str, Attrs] = {}
        if game["deck_dir"]:
            with self._connect() as fs:
                remote = fs.walk_attrs(game["deck_dir"])
        base = snap or {}
        local_changed, remote_changed, conflicts = [], [], []
        for rel in sorted(set(local) | set(remote)):
            b, l, r = base.get(rel), local.get(rel), remote.get(rel)
            lc = l is not None and l != b and l != r
            rc = r is not None and r != b and r != l
            if lc and rc:
                conflicts.append(rel)
            elif lc:
                local_changed.append(rel)
            elif rc:
                remote_changed.append(rel)
        return SyncStatus(
            synced_before=snap is not None, local_dir=str(local_dir),
            local_changed=local_changed, remote_changed=remote_changed, conflicts=conflicts,
        )

    # ---- 更新データの適用 ----

    def plan_update(self, game_id: int, source: str, root: str | None = None) -> UpdatePlan:
        """更新データ（展開済みのフォルダ）を作品フォルダに重ねたときの変化を調べる（まだ書き込まない）。

        root を省略すると、作品フォルダに当たる位置を自動で選ぶ。
        """
        game = self._db.get(game_id)
        local_dir = self._local_dir(game)
        if not local_dir.is_dir():
            raise ValueError("PC側の作品フォルダがありません。先に「Deckから取得」してください。")
        src = Path(source)
        if not src.is_dir():
            raise NotFoundError(f"フォルダが見つかりません: {source}")
        if _is_inside(src, local_dir) or _is_inside(local_dir, src):
            raise ValueError("作品フォルダそのもの（またはその中・外側）は更新データにできません。")

        files = _local_files(src)
        auto_root, exe_found = _find_root(files, game["exe"], local_dir)
        candidates = root_candidates(files)
        if root is None:
            root = auto_root
        elif root not in candidates:
            raise ValueError(f"更新データの中にないフォルダです: {root}")
        else:
            exe_found = bool(game["exe"]) and (src / root / game["exe"]).is_file()
        prefix = f"{root}/" if root else ""
        entries, new, changed, same = [], 0, 0, 0
        for rel in files:
            if not rel.startswith(prefix):
                continue
            target = rel[len(prefix):]
            s, d = src / rel, local_dir / target
            if not d.exists():
                status = "new"
                new += 1
            elif d.stat().st_size == s.stat().st_size and filecmp.cmp(s, d, shallow=False):
                same += 1
                continue
            else:
                status = "changed"
                changed += 1
            if len(entries) < _LIST_LIMIT:
                entries.append(UpdateFile(path=target, status=status, size=s.stat().st_size))
        return UpdatePlan(
            source=str(src), root=root, root_candidates=candidates, exe_found=exe_found,
            version=_guess_version(src.name) or _guess_version(PurePosixPath(root).name if root else ""),
            new=new, changed=changed, same=same, files=entries,
        )

    def apply_update(self, game_id: int, source: str, root: str, version: str = "", job: Job | None = None) -> ApplyResult:
        """更新データを作品フォルダに重ねる（追加・変更されたファイルだけを上書きし、何も削除しない）。"""
        game = self._db.get(game_id)
        local_dir = self._local_dir(game)
        self.plan_update(game_id, source, root)  # 位置などを確かめ直す
        src = Path(source) / root if root else Path(source)
        targets = [
            rel for rel in _local_files(src)
            if not (local_dir / rel).exists()
            or (local_dir / rel).stat().st_size != (src / rel).stat().st_size
            or not filecmp.cmp(src / rel, local_dir / rel, shallow=False)
        ]
        for i, rel in enumerate(targets, 1):
            dest = local_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".part")
            shutil.copy2(src / rel, tmp)
            # 元のファイルと同じ更新日時だと、Deckへ反映するときに変更として扱われないことがあるので現在時刻にする
            os.utime(tmp, None)
            tmp.replace(dest)
            if job:
                job.progress(i, len(targets))
        if job:
            job.log(f"{len(targets)}ファイルを更新しました。")
        if version:
            self._db.update(game_id, {"version": version})
        return ApplyResult(copied=len(targets), version=version, exe_exists=bool(game["exe"]) and (local_dir / game["exe"]).exists())

    # ---- Deckへ反映 ----

    def push(self, game_id: int, job: Job | None = None, base: str | None = None, force: bool = False) -> PushResult:
        """PCで変わったファイルをDeckへ送る。Deckでだけ変わったファイルは送らない（Deckを正とする）。

        Deckに作品フォルダが無いとき（PCから初めて送るとき）は base の格納先に作る。
        force=True なら、PCとDeckの両方で変わったファイルもPCの内容で上書きする。
        """
        game = self._db.get(game_id)
        local_dir = self._local_dir(game)
        if not local_dir.is_dir():
            raise ValueError("PC上の作品フォルダが見つかりません。")
        deck_dir = game["deck_dir"]
        if not deck_dir:
            bases = self._get_config().steam_deck.doujin_base
            if not bases:
                raise ValueError("設定画面で、Deckの同人ゲーム格納先を登録してください。")
            if base not in bases:
                raise ValueError(f"格納先を選んでください（候補: {', '.join(bases)}）。")
            deck_dir = f"{base.rstrip('/')}/{local_dir.name}"

        snap = self._snapshots.get(game_id)
        local = _local_attrs(local_dir)
        with self._connect() as fs:
            remote = fs.walk_attrs(deck_dir)
            if snap is None and remote:
                raise ValueError("Deck上の作品を正とするため、先に「Deckから取得」を実行してください。")
            snap = snap or {}
            tasks, kept, conflicts, unchanged = [], [], [], 0
            for rel, cur in sorted(local.items()):
                b, r = snap.get(rel), remote.get(rel)
                if cur == r:
                    unchanged += 1
                    snap[rel] = r
                    continue
                if cur == b:
                    kept.append(rel)  # PCは前回のまま、Deckだけが変わった
                    continue
                if r is None or r == b or force:
                    tasks.append((local_dir / rel, f"{deck_dir.rstrip('/')}/{rel}"))
                else:
                    conflicts.append(rel)
            if job:
                job.log(f"送信先: {deck_dir}/（{len(tasks)}ファイルを送信）")
            res = fs.upload(tasks, overwrite=True, on_progress=job.progress if job else None)
            after = fs.walk_attrs(deck_dir) if tasks else remote

        failed = {e.split(":", 1)[0] for e in res.errors}
        for local_path, _remote in tasks:
            rel = local_path.relative_to(local_dir).as_posix()
            if local_path.name not in failed and rel in after:
                snap[rel] = after[rel]
        self._snapshots.save(game_id, snap)
        changes: dict = {"deck_dir": deck_dir}
        if not res.errors:
            changes["transferred_at"] = datetime.now()
        if not game["local_path"]:
            changes["local_path"] = str(local_dir)
        self._db.update(game_id, changes)
        for e in res.errors:
            if job:
                job.log(f"失敗: {e}")
        return PushResult(
            deck_dir=deck_dir, pushed=res.transferred, unchanged=unchanged,
            kept_remote=kept, conflicts=conflicts, errors=res.errors,
        )


def _local_files(folder: Path) -> list[str]:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file() and not p.name.endswith(".part"))


def _local_attrs(folder: Path) -> dict[str, Attrs]:
    if not folder.is_dir():
        return {}
    out = {}
    for rel in _local_files(folder):
        st = (folder / rel).stat()
        out[rel] = (st.st_size, int(st.st_mtime))
    return out


def _find_root(files: list[str], exe: str, local_dir: Path) -> tuple[str, bool]:
    """更新データの中で、作品フォルダに当たるフォルダを探す。

    台帳の起動ファイル（例: maid/Game.exe）と同じ相対位置のファイルがあれば、それを基準にする
    （"作品名_v1.4/maid/Game.exe" なら "作品名_v1.4"）。無いとき（差分パッチなど）は、
    重ねたときにPCの作品フォルダのファイル・フォルダと最もよく一致する位置を選ぶ。
    """
    exe = exe.strip("/").lower()
    if exe:
        roots = [f[: len(f) - len(exe)].rstrip("/") for f in files if f.lower() == exe or f.lower().endswith("/" + exe)]
        if roots:
            return min(roots, key=len), True

    candidates = {""}
    for f in files:
        parts = f.split("/")[:-1]
        for i in range(1, min(len(parts), 4) + 1):
            candidates.add("/".join(parts[:i]))

    def score(root: str) -> int:
        prefix = f"{root}/" if root else ""
        total = 0
        for f in files:
            if not f.startswith(prefix):
                continue
            target = f[len(prefix):]
            if (local_dir / target).is_file():
                total += 2  # 同じファイルがある（上書きになる）
            elif "/" in target and (local_dir / target).parent.is_dir():
                total += 1  # 同じフォルダがある（追加になる）
        return total

    best = max(sorted(candidates, key=lambda r: (r.count("/"), r)), key=score)
    if score(best) > 0:
        return best, False
    # どこにも一致しない（新しいフォルダだけのパッチなど）ときは、中身が1つだけの包みのフォルダを外す
    root = ""
    while True:
        prefix = f"{root}/" if root else ""
        children = {f[len(prefix):].split("/", 1)[0] for f in files if f.startswith(prefix)}
        direct_files = [f for f in files if f.startswith(prefix) and "/" not in f[len(prefix):]]
        if len(children) != 1 or direct_files:
            return root, False
        root = f"{prefix}{children.pop()}"


def root_candidates(files: list[str]) -> list[str]:
    """更新データの中で、作品フォルダとして選べる位置（フォルダの深さ3まで）。"""
    out = {""}
    for f in files:
        parts = f.split("/")[:-1]
        for i in range(1, min(len(parts), 3) + 1):
            out.add("/".join(parts[:i]))
    return sorted(out, key=lambda r: (r.count("/"), r))


def _guess_version(name: str) -> str:
    m = _VERSION.search(name)
    return m.group(1).replace("_", ".") if m else ""


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False
