"""同人ゲーム台帳（PCのSQLiteが正本）の管理と、Steam Deckへの転送。"""
from __future__ import annotations

import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable

from pydantic import BaseModel

from kakehashi.config import Config
from kakehashi.domain.doujin import (
    IMAGE_KINDS, DoujinGame, DoujinImage, DoujinPatch, FolderGuess, guess_from_folder_name,
    rank_exe_candidates,
)
from kakehashi.domain.media import IMAGE_SUFFIXES
from kakehashi.errors import NotFoundError
from kakehashi.domain.works import WorkHit, WorkInfo
from kakehashi.infra import dlsite, dmm, downloader
from kakehashi.infra.deck import DeckConnector
from kakehashi.infra.doujin_db import DoujinDB
from kakehashi.services.jobs import Job


class FolderCandidate(BaseModel):
    path: str
    name: str
    guess: FolderGuess
    registered_id: int | None = None


class SearchResult(BaseModel):
    hits: list[WorkHit] = []
    errors: dict[str, str] = {}
    """販売サイトごとの検索エラー"""


class DeckFolder(BaseModel):
    base: str
    name: str
    path: str
    guess: FolderGuess
    linked_id: int | None = None
    """このフォルダを deck_dir に持つ台帳の作品。"""
    match_id: int | None = None
    """まだDeckと紐づいていない台帳の作品のうち、同じ作品と思われるもの（取り込むと紐づける）。"""


class DoujinService:
    def __init__(
        self, get_config: Callable[[], Config], connect: DeckConnector, db: DoujinDB, images_dir: Path,
    ) -> None:
        self._get_config = get_config
        self._connect = connect
        self._db = db
        self._images_dir = images_dir

    # ---- 参照 ----

    def list(self) -> list[DoujinGame]:
        return [self._model(row) for row in self._db.list()]

    def get(self, game_id: int) -> DoujinGame:
        return self._model(self._db.get(game_id))

    def _model(self, row: dict) -> DoujinGame:
        return DoujinGame(**row, images=self._images(row["id"]))

    # ---- 登録・編集 ----

    def register_folder(self, path: str) -> DoujinGame:
        folder = Path(path)
        if not folder.is_dir():
            raise NotFoundError(f"フォルダが見つかりません: {path}")
        if (existing := self._find_by_local_path(folder)) is not None:
            raise ValueError(f"このフォルダは登録済みです（{existing['title']}）。")
        guess = guess_from_folder_name(folder.name)
        exes = rank_exe_candidates(_local_files(folder))
        row = self._db.create({
            **guess.model_dump(), "local_path": str(folder), "exe": exes[0] if exes else "",
        })
        return self._model(row)

    def scan_parent(self, parent: str) -> list[FolderCandidate]:
        """親フォルダ直下の作品フォルダを列挙し、登録済みかどうかを添えて返す。"""
        root = Path(parent)
        if not root.is_dir():
            raise NotFoundError(f"フォルダが見つかりません: {parent}")
        registered = {_norm(r["local_path"]): r["id"] for r in self._db.list() if r["local_path"]}
        return [
            FolderCandidate(
                path=str(d), name=d.name, guess=guess_from_folder_name(d.name),
                registered_id=registered.get(_norm(str(d))),
            )
            for d in sorted(root.iterdir(), key=lambda p: p.name.lower())
            if d.is_dir() and not d.name.startswith(".")
        ]

    def register_many(self, paths: list[str]) -> list[DoujinGame]:
        created = []
        for p in paths:
            if self._find_by_local_path(Path(p)) is None:
                created.append(self.register_folder(p))
        return created

    def update(self, game_id: int, patch: DoujinPatch) -> DoujinGame:
        changes = patch.changes()
        if "tags" in changes:
            # 空白の除去と重複の排除（順序は保つ）
            changes["tags"] = list(dict.fromkeys(t.strip() for t in changes["tags"] or [] if t.strip()))
        if "exe" in changes:
            changes["exe"] = (changes["exe"] or "").replace("\\", "/").lstrip("/")
        return self._model(self._db.update(game_id, changes))

    def delete(self, game_id: int) -> None:
        """台帳から削除する（PCやDeckのゲーム本体には触れない）。"""
        self._db.delete(game_id)
        shutil.rmtree(self._images_dir / str(game_id), ignore_errors=True)

    def exe_candidates(self, game_id: int) -> list[str]:
        game = self._db.get(game_id)
        local = Path(game["local_path"]) if game["local_path"] else None
        if local and local.is_dir():
            return rank_exe_candidates(_local_files(local))
        if game["deck_dir"]:
            with self._connect() as fs:
                return rank_exe_candidates(_remote_rel_files(fs, game["deck_dir"]))
        return []

    def _find_by_local_path(self, folder: Path) -> dict | None:
        key = _norm(str(folder))
        return next((r for r in self._db.list() if r["local_path"] and _norm(r["local_path"]) == key), None)

    # ---- 画像 ----

    def _images(self, game_id: int) -> dict[str, DoujinImage]:
        d = self._images_dir / str(game_id)
        if not d.is_dir():
            return {}
        out = {}
        for p in sorted(d.iterdir()):
            if p.is_file() and p.stem in IMAGE_KINDS and not p.name.endswith(".part"):
                out[p.stem] = DoujinImage(kind=p.stem, filename=p.name, mtime=p.stat().st_mtime)
        return out

    def image_path(self, game_id: int, kind: str) -> Path:
        img = self._images(game_id).get(_kind(kind))
        if img is None:
            raise NotFoundError(f"{kind} の画像がありません。")
        return self._images_dir / str(game_id) / img.filename

    def import_image_file(self, game_id: int, kind: str, source: Path) -> DoujinGame:
        if not source.is_file():
            raise NotFoundError(f"ファイルが見つかりません: {source}")
        return self._store_image(game_id, kind, source.suffix.lower(), lambda dest: shutil.copy2(source, dest))

    def import_image_url(self, game_id: int, kind: str, url: str) -> DoujinGame:
        if not url.startswith(("http://", "https://")):
            raise ValueError("http:// または https:// で始まるURLを指定してください。")
        data, suffix = downloader.download_file(url)
        return self._store_image(game_id, kind, suffix, lambda dest: dest.write_bytes(data))

    def delete_image(self, game_id: int, kind: str) -> DoujinGame:
        self.image_path(game_id, kind).unlink()
        return self.get(game_id)

    def _store_image(self, game_id: int, kind: str, suffix: str, write: Callable[[Path], object]) -> DoujinGame:
        kind = _kind(kind)
        self._db.get(game_id)  # 存在確認
        if suffix not in IMAGE_SUFFIXES:
            raise ValueError(f"画像ファイルではありません（{suffix or '拡張子なし'}）。")
        d = self._images_dir / str(game_id)
        d.mkdir(parents=True, exist_ok=True)
        dest = d / f"{kind}{suffix}"
        tmp = dest.with_name(dest.name + ".part")
        try:
            write(tmp)
            tmp.replace(dest)
        finally:
            tmp.unlink(missing_ok=True)
        for old in d.glob(f"{kind}.*"):
            if old != dest and not old.name.endswith(".part"):
                old.unlink()
        return self.get(game_id)

    # ---- DLsite ----

    def fetch_work(self, store: str, work_id: str) -> WorkInfo:
        """販売サイトの作品ページから作品情報を取得する。"""
        work_id = work_id.strip()
        if store == "dlsite":
            return dlsite.fetch(work_id)
        if store == "fanza":
            return dmm.fetch_doujin(work_id)
        if store in ("fanza_games", "dmm_games"):
            return dmm.fetch_pcgame(work_id, store)
        raise ValueError(f"作品情報を取得できない販売サイトです: {store or '（未設定）'}")

    def search_works(self, keyword: str, stores: list[str] | None = None) -> SearchResult:
        """タイトルで各販売サイトを並行して検索する。失敗したサイトはエラーとして返し、他の結果は返す。"""
        keyword = keyword.strip()
        if not keyword:
            raise ValueError("検索する言葉を入力してください。")
        searchers = {
            "dlsite": lambda: dlsite.search(keyword),
            "fanza": lambda: dmm.search_doujin(keyword),
            "fanza_games": lambda: dmm.search_pcgame(keyword, "fanza_games"),
            "dmm_games": lambda: dmm.search_pcgame(keyword, "dmm_games"),
        }
        targets = [s for s in (stores or list(searchers)) if s in searchers]
        result = SearchResult()
        with ThreadPoolExecutor(max_workers=len(targets) or 1) as pool:
            futures = {s: pool.submit(searchers[s]) for s in targets}
            for store, fut in futures.items():
                try:
                    result.hits.extend(fut.result())
                except Exception as e:
                    result.errors[store] = str(e) or type(e).__name__
        return result

    # ---- Steam Deck ----

    def transfer(self, game_id: int, job: Job, base: str | None = None, overwrite: bool = False) -> dict:
        """PCの作品フォルダをDeckへ送る。2回目以降は前回と同じフォルダへ差分だけを送る。"""
        game = self._db.get(game_id)
        local = Path(game["local_path"]) if game["local_path"] else None
        if local is None or not local.is_dir():
            raise ValueError("PC上の作品フォルダが設定されていないか、見つかりません。")
        remote_dir = game["deck_dir"]
        if not remote_dir:
            bases = self._get_config().steam_deck.doujin_base
            if not bases:
                raise ValueError("設定画面で、Deckの同人ゲーム格納先を登録してください。")
            if base not in bases:
                raise ValueError(f"格納先を選んでください（候補: {', '.join(bases)}）。")
            remote_dir = f"{base.rstrip('/')}/{local.name}"

        tasks = [(local / rel, f"{remote_dir}/{rel}") for rel in _local_files(local)]
        job.log(f"送信先: {remote_dir}/（{len(tasks)}ファイル）")
        with self._connect() as fs:
            res = fs.upload(tasks, overwrite=overwrite, on_progress=job.progress)
        for e in res.errors:
            job.log(f"失敗: {e}")
        if not res.errors:
            self._db.update(game_id, {"deck_dir": remote_dir, "transferred_at": datetime.now()})
        elif not game["deck_dir"]:
            self._db.update(game_id, {"deck_dir": remote_dir})
        return {"deck_dir": remote_dir, "transferred": res.transferred, "skipped": res.skipped, "errors": res.errors}

    def scan_deck(self) -> list[DeckFolder]:
        """Deckの格納先にある作品フォルダを列挙し、台帳と紐づいているかを添えて返す。"""
        rows = self._db.list()
        linked = {r["deck_dir"].rstrip("/"): r["id"] for r in rows if r["deck_dir"]}
        result = []
        with self._connect() as fs:
            for base in self._get_config().steam_deck.doujin_base:
                base = base.rstrip("/")
                for name in fs.list_dirs(base):
                    path = f"{base}/{name}"
                    guess = guess_from_folder_name(name)
                    linked_id = linked.get(path)
                    result.append(DeckFolder(
                        base=base, name=name, path=path, guess=guess, linked_id=linked_id,
                        match_id=None if linked_id else _match_unlinked(rows, name, guess.work_id),
                    ))
        return result

    def import_from_deck(self, paths: list[str]) -> list[DoujinGame]:
        """Deckの作品フォルダを台帳に取り込む。

        同じ作品と思われる未紐づけの作品が台帳にあれば、新しく作らずにそこへ deck_dir を設定する。
        無ければPC側のフォルダは空のまま新規登録する。
        """
        bases = [b.rstrip("/") for b in self._get_config().steam_deck.doujin_base]
        result = []
        with self._connect() as fs:
            for path in paths:
                path = path.rstrip("/")
                if not any(path.startswith(f"{b}/") for b in bases):
                    raise ValueError(f"格納先の外にあるフォルダは取り込めません: {path}")
                rows = self._db.list()
                if any(r["deck_dir"].rstrip("/") == path for r in rows):
                    continue
                name = PurePosixPath(path).name
                guess = guess_from_folder_name(name)
                exes = rank_exe_candidates(_remote_rel_files(fs, path))
                if (match := _match_unlinked(rows, name, guess.work_id)) is not None:
                    current = self._db.get(match)
                    row = self._db.update(match, {"deck_dir": path, **({} if current["exe"] or not exes else {"exe": exes[0]})})
                else:
                    row = self._db.create({**guess.model_dump(), "deck_dir": path, "exe": exes[0] if exes else ""})
                result.append(self._model(row))
        return result


def _match_unlinked(rows: list[dict], folder_name: str, work_id: str) -> int | None:
    """Deckと未紐づけの作品から、作品IDかPC側のフォルダ名が一致するものを探す。"""
    for r in rows:
        if r["deck_dir"]:
            continue
        if work_id and r["work_id"].upper() == work_id.upper():
            return r["id"]
        if r["local_path"] and Path(r["local_path"]).name == folder_name:
            return r["id"]
    return None


def _kind(kind: str) -> str:
    if kind not in IMAGE_KINDS:
        raise ValueError(f"不明な画像の種類です: {kind}")
    return kind


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _local_files(folder: Path) -> list[str]:
    """フォルダ配下のファイルを、フォルダからの相対パス（区切りは /）で返す。"""
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


def _remote_rel_files(fs, remote_dir: str) -> list[str]:
    prefix = remote_dir.rstrip("/") + "/"
    return [p[len(prefix):] for p in fs.walk_files(remote_dir) if p.startswith(prefix)]
