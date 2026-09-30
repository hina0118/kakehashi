"""ES-DEのメディア（PC側のdownloaded_mediaが正本）の参照・登録・生成・Deckとの同期。"""
from __future__ import annotations

import io
import shutil
import tempfile
from functools import cached_property
from pathlib import Path
from typing import Callable

from PIL import Image
from pydantic import BaseModel

from kakehashi.config import Config, data_dir
from kakehashi.domain.media import (
    MEDIA_FOLDERS, GameMedia, MediaFile, media_kind, rom_stem, validate_folder,
)
from kakehashi.errors import NotFoundError
from kakehashi.infra import downloader, media_store
from kakehashi.infra.deck import DeckConnector
from kakehashi.services.jobs import Job
from kakehashi.services.previews import PreviewInfo, PreviewStore


class SyncResult(BaseModel):
    transferred: int
    skipped: int
    deleted: int = 0
    errors: list[str]


class Capabilities(BaseModel):
    ai_logo: bool
    ytdlp: bool


class MediaService:
    def __init__(
        self,
        get_config: Callable[[], Config],
        connect: DeckConnector,
        pending: media_store.PendingDeletions,
        previews: PreviewStore,
    ) -> None:
        self._get_config = get_config
        self._connect = connect
        self._pending = pending
        self._previews = previews

    # ---- 参照 ----

    def base_dir(self, system: str) -> Path:
        config = self._get_config()
        if not config.windows.media_base:
            raise ValueError("PC側のメディアフォルダ（windows.media_base）が設定されていません。")
        return config.local_media_dir(system)

    def game_media(self, system: str, path: str) -> GameMedia:
        base, stem = self.base_dir(system), rom_stem(path)
        files: dict[str, MediaFile | None] = {}
        for folder in MEDIA_FOLDERS:
            found = media_store.find_files(base, folder, stem)
            files[folder] = _to_media_file(folder, found[0]) if found else None
        return GameMedia(path=path, stem=stem, files=files)

    def coverage(self, system: str) -> dict[str, dict[str, str]]:
        return media_store.scan(self.base_dir(system))

    def file_path(self, system: str, folder: str, filename: str) -> Path:
        validate_folder(folder)
        if not filename or "/" in filename or "\\" in filename or filename in (".", ".."):
            raise ValueError(f"不正なファイル名です: {filename}")
        p = self.base_dir(system) / folder / filename
        if not p.is_file():
            raise NotFoundError(f"ファイルがありません: {folder}/{filename}")
        return p

    def pending_deletions(self, system: str) -> list[str]:
        return sorted(self._pending.get(system))

    @cached_property
    def capabilities(self) -> Capabilities:
        from kakehashi.imaging import logo_extractor
        return Capabilities(ai_logo=logo_extractor.is_available(), ytdlp=downloader.ytdlp_available())

    # ---- 登録・削除 ----

    def import_file(self, system: str, path: str, folder: str, source: Path) -> MediaFile:
        if not source.is_file():
            raise NotFoundError(f"ファイルが見つかりません: {source}")
        return self._store(system, path, folder, source.suffix.lower(), lambda dest: shutil.copy2(source, dest))

    def import_url(self, system: str, path: str, folder: str, url: str) -> MediaFile:
        if not url.startswith(("http://", "https://")):
            raise ValueError("http:// または https:// で始まるURLを指定してください。")
        if folder == "videos" and downloader.ytdlp_available():
            with tempfile.TemporaryDirectory(dir=data_dir()) as tmp:
                got = downloader.download_with_ytdlp(url, Path(tmp), "video")
                return self._store(system, path, folder, got.suffix.lower(), lambda dest: shutil.move(got, dest))
        data, suffix = downloader.download_file(url)
        return self._store(system, path, folder, suffix, lambda dest: dest.write_bytes(data))

    def delete(self, system: str, path: str, folder: str) -> int:
        """ゲームの指定フォルダのメディアを削除し、Deckからも消すよう記録する。削除件数を返す。"""
        validate_folder(folder)
        found = media_store.find_files(self.base_dir(system), folder, rom_stem(path))
        for p in found:
            p.unlink()
            self._pending.add(system, f"{folder}/{p.name}")
        return len(found)

    def _store(self, system: str, path: str, folder: str, suffix: str, write: Callable[[Path], object]) -> MediaFile:
        validate_folder(folder)
        if not suffix:
            raise ValueError("ファイルの拡張子を判定できません。")
        base, stem = self.base_dir(system), rom_stem(path)
        dest = base / folder / f"{stem}{suffix}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        try:
            write(tmp)
            tmp.replace(dest)
        finally:
            tmp.unlink(missing_ok=True)
        # 拡張子違いの旧ファイルは差し替えとして削除し、Deckからも消す
        for old in media_store.find_files(base, folder, stem):
            if old != dest:
                old.unlink()
                self._pending.add(system, f"{folder}/{old.name}")
        self._pending.discard(system, {f"{folder}/{dest.name}"})
        return _to_media_file(folder, dest)

    # ---- 画像生成（プレビュー → 保存） ----

    def _source_image(self, system: str, path: str, folder: str) -> Image.Image:
        found = media_store.find_files(self.base_dir(system), folder, rom_stem(path))
        if not found:
            raise NotFoundError(f"{folder} の画像がありません。")
        return Image.open(found[0]).convert("RGBA")

    def preview_3dbox(
        self, system: str, path: str, *,
        spine_ratio: float = 0.08, angle_pct: float = 0.30, shadow: bool = True, spine_text: str = "",
    ) -> PreviewInfo:
        from kakehashi.imaging.box3d import decorators_for, generate_3dbox

        decorate_cover, decorate_spine = decorators_for(system)
        img = generate_3dbox(
            self._source_image(system, path, "covers"),
            spine_ratio=spine_ratio, angle_pct=angle_pct, shadow=shadow,
            spine_text=spine_text, system=system,
            decorate_cover=decorate_cover, decorate_spine=decorate_spine,
        )
        return self._previews.put(img)

    def preview_miximage(self, system: str, path: str) -> PreviewInfo:
        from kakehashi.imaging.miximage import generate_miximage

        media = self.game_media(system, path)
        base = self.base_dir(system)

        def src(folder: str) -> Path | None:
            f = media.files[folder]
            return base / folder / f.filename if f else None

        screenshot = src("screenshots")
        if screenshot is None:
            raise NotFoundError("miximage の生成には screenshots が必要です。")
        img = generate_miximage(
            screenshot_path=screenshot, marquee_path=src("marquees"),
            box3d_path=src("3dboxes"), physicalmedia_path=src("physicalmedia"),
        )
        return self._previews.put(img)

    def preview_crop(self, system: str, path: str, folder: str, box: tuple[int, int, int, int]) -> PreviewInfo:
        """画像の一部を切り出す（例: covers からロゴ部分を切り出して marquees に使う）。"""
        img = self._source_image(system, path, folder)
        x1, y1, x2, y2 = box
        x1, x2 = sorted((max(0, x1), min(img.width, x2)))
        y1, y2 = sorted((max(0, y1), min(img.height, y2)))
        if x2 - x1 < 5 or y2 - y1 < 5:
            raise ValueError("切り出し範囲が小さすぎます。")
        return self._previews.put(img.crop((x1, y1, x2, y2)))

    def preview_ai_logo(self, system: str, path: str) -> PreviewInfo:
        """covers からAIでロゴを検出し、背景を除去した透過画像を作る（NVIDIA GPUが必要）。"""
        from kakehashi.imaging import logo_extractor

        if not logo_extractor.is_available():
            raise ValueError("AIロゴ抽出には CUDA 対応の GPU と追加パッケージ（uv sync --extra ai）が必要です。")
        logo = logo_extractor.extract_logo(self._source_image(system, path, "covers"), transparent=True)
        if logo is None:
            raise NotFoundError("ロゴを検出できませんでした。範囲を指定して切り出してください。")
        return self._previews.put(logo)

    def preview_bytes(self, preview_id: str) -> bytes:
        return self._previews.get(preview_id)

    def save_preview(self, system: str, path: str, folder: str, preview_id: str) -> MediaFile:
        data = self._previews.get(preview_id)
        return self._store(system, path, folder, ".png", lambda dest: dest.write_bytes(data))

    # ---- Deckとの同期 ----

    def pull(self, system: str, job: Job, overwrite: bool = False) -> SyncResult:
        """DeckのメディアをPCへ取得する。

        PCに同じゲーム・同じ種類のファイルがあれば取得しない（PCでの編集を上書きしない）。
        overwrite=True のときは、同名でサイズの異なるファイルをDeck側の内容で上書きする。
        """
        base = self.base_dir(system)
        remote_root = self._get_config().steam_deck.media_dir(system)
        pending = self._pending.get(system)
        local = media_store.scan(base)
        tasks: list[tuple[str, Path]] = []
        skipped = 0
        job.log("Deckのメディアを確認しています…")
        with self._connect() as fs:
            for folder in MEDIA_FOLDERS:
                for name, size in fs.list_files(f"{remote_root}/{folder}").items():
                    dest = base / folder / name
                    existing = local.get(Path(name).stem, {}).get(folder)
                    if f"{folder}/{name}" in pending:
                        skipped += 1
                    elif existing is None or (overwrite and existing == name and dest.stat().st_size != size):
                        tasks.append((f"{remote_root}/{folder}/{name}", dest))
                    else:
                        skipped += 1
            job.log(f"取得するファイル: {len(tasks)}件（取得済み・対象外: {skipped}件）")
            res = fs.download(tasks, on_progress=job.progress)
        for e in res.errors:
            job.log(f"失敗: {e}")
        return SyncResult(transferred=res.transferred, skipped=skipped, errors=res.errors)

    def push(self, system: str, job: Job, folders: list[str] | None = None, overwrite: bool = False) -> SyncResult:
        """PCのメディアをDeckへ反映する。記録済みの削除を先に適用し、サイズの異なるファイルだけ送る。"""
        base = self.base_dir(system)
        remote_root = self._get_config().steam_deck.media_dir(system)
        targets = [validate_folder(f) for f in (folders or MEDIA_FOLDERS)]
        with self._connect() as fs:
            deleted_rels: set[str] = set()
            for rel in sorted(self._pending.get(system)):
                try:
                    fs.remove(f"{remote_root}/{rel}")
                except FileNotFoundError:
                    pass
                deleted_rels.add(rel)
            self._pending.discard(system, deleted_rels)
            if deleted_rels:
                job.log(f"Deckから削除: {len(deleted_rels)}件")

            tasks: list[tuple[Path, str]] = []
            skipped = 0
            for folder in targets:
                remote = fs.list_files(f"{remote_root}/{folder}")
                for p in media_store.list_folder(base / folder):
                    if overwrite or remote.get(p.name) != p.stat().st_size:
                        tasks.append((p, f"{remote_root}/{folder}/{p.name}"))
                    else:
                        skipped += 1
            job.log(f"送信するファイル: {len(tasks)}件（送信済み: {skipped}件）")
            res = fs.upload(tasks, overwrite=True, on_progress=job.progress)
        for e in res.errors:
            job.log(f"失敗: {e}")
        return SyncResult(transferred=res.transferred, skipped=skipped, deleted=len(deleted_rels), errors=res.errors)


def _to_media_file(folder: str, p: Path) -> MediaFile:
    st = p.stat()
    return MediaFile(folder=folder, filename=p.name, size=st.st_size, mtime=st.st_mtime, kind=media_kind(p.name))


def image_thumbnail(path: Path, width: int) -> bytes:
    """一覧表示用の縮小画像（PNG）。"""
    with Image.open(path) as img:
        img.thumbnail((width, width * 2))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()
