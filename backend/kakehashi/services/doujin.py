"""同人ゲーム台帳（PCのSQLiteが正本）の管理と、Steam Deckへの転送。"""
from __future__ import annotations

import io
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from typing import Callable

from PIL import Image
from pydantic import BaseModel

from kakehashi.config import Config
from kakehashi.domain.doujin import (
    IMAGE_KINDS, DoujinGame, DoujinImage, DoujinPatch, FolderGuess, guess_from_folder_name,
    rank_exe_candidates, title_key,
)
from kakehashi.domain.media import IMAGE_SUFFIXES
from kakehashi.domain.tags import normalize_tags
from kakehashi.errors import NotFoundError
from kakehashi.domain.works import WorkHit, WorkInfo
from kakehashi.infra import dlsite, dmm, downloader
from kakehashi.infra.deck import DeckConnector
from kakehashi.infra.doujin_db import DoujinDB


class DuplicateHit(BaseModel):
    """登録しようとしているフォルダと同じ作品かもしれない、台帳の作品。"""
    id: int
    title: str
    reasons: list[str]
    """一致したもの: work_id（作品ID）/ folder（フォルダ名）/ title（タイトル）"""
    deck_dir: str
    has_local: bool
    """PC側の作品フォルダがあるか（無ければ更新データを適用する前に「Deckから取得」が要る）"""


class FolderCandidate(BaseModel):
    path: str
    name: str
    guess: FolderGuess
    registered_id: int | None = None
    duplicates: list[DuplicateHit] = []


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
        rows = self._db.list()
        registered = {_norm(r["local_path"]): r["id"] for r in rows if r["local_path"]}
        out = []
        for d in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            registered_id = registered.get(_norm(str(d)))
            out.append(FolderCandidate(
                path=str(d), name=d.name, guess=guess_from_folder_name(d.name), registered_id=registered_id,
                duplicates=[] if registered_id is not None else self._duplicates(d, rows),
            ))
        return out

    def find_duplicates(self, path: str) -> list[DuplicateHit]:
        """登録しようとしているフォルダと同じ作品かもしれない台帳の作品を探す。"""
        folder = Path(path)
        if not folder.is_dir():
            raise NotFoundError(f"フォルダが見つかりません: {path}")
        return self._duplicates(folder, self._db.list())

    def _duplicates(self, folder: Path, rows: list[dict]) -> list[DuplicateHit]:
        guess = guess_from_folder_name(folder.name)
        # 作品IDはフォルダ名に無ければ親フォルダ名からも探す（"d_586735/dungeon_nante" のような置き方）
        work_id = (guess.work_id or guess_from_folder_name(folder.parent.name).work_id).casefold()
        name = folder.name.casefold()
        key = title_key(guess.title)
        pc_base = self._get_config().windows.doujin_base
        hits = []
        for r in rows:
            if r["local_path"] and _norm(r["local_path"]) == _norm(str(folder)):
                continue
            reasons = []
            if work_id and r["work_id"].casefold() == work_id:
                reasons.append("work_id")
            names = {PurePosixPath(r["deck_dir"]).name, Path(r["local_path"]).name if r["local_path"] else ""}
            if name in {n.casefold() for n in names if n}:
                reasons.append("folder")
            if len(key) >= 2 and title_key(r["title"]) == key:
                reasons.append("title")
            if reasons:
                local = Path(r["local_path"]) if r["local_path"] else (
                    Path(pc_base) / PurePosixPath(r["deck_dir"]).name if pc_base and r["deck_dir"] else None
                )
                hits.append(DuplicateHit(
                    id=r["id"], title=r["title"], reasons=reasons, deck_dir=r["deck_dir"],
                    has_local=bool(local and local.is_dir()),
                ))
        return hits

    def register_many(self, paths: list[str]) -> list[DoujinGame]:
        created = []
        for p in paths:
            if self._find_by_local_path(Path(p)) is None:
                created.append(self.register_folder(p))
        return created

    def update(self, game_id: int, patch: DoujinPatch) -> DoujinGame:
        changes = patch.changes()
        if "tags" in changes:
            # 空白の除去・表記ゆれの統一・重複の排除（順序は保つ）
            changes["tags"] = normalize_tags(changes["tags"] or [])
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

    def import_image_bytes(self, game_id: int, kind: str, data: bytes, suffix: str) -> DoujinGame:
        """画像データを登録する。ブラウザで表示できない形式（.ico など）はPNGに変換する。"""
        try:
            with Image.open(io.BytesIO(data)) as img:
                img.load()
                if suffix.lower() not in IMAGE_SUFFIXES or suffix.lower() == ".tga":
                    buf = io.BytesIO()
                    # .ico は複数サイズを含むので、最も大きいものを使う
                    if getattr(img, "ico", None) is not None:
                        img = img.ico.getimage(max(img.ico.sizes()))
                    img.save(buf, "PNG")
                    data, suffix = buf.getvalue(), ".png"
        except Exception as e:
            raise ValueError(f"画像として読み込めませんでした: {e}") from e
        return self._store_image(game_id, kind, suffix.lower(), lambda dest: dest.write_bytes(data))

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
        """販売サイトの作品ページから作品情報を取得する。ジャンルは台帳のタグの表記にそろえる。"""
        info = self._fetch_work(store, work_id.strip())
        return info.model_copy(update={"genres": normalize_tags(info.genres)})

    def _fetch_work(self, store: str, work_id: str) -> WorkInfo:
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
