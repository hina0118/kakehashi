from __future__ import annotations

from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel

# ES-DEのdownloaded_media/{機種}/ 配下のフォルダ
MEDIA_FOLDERS = (
    "3dboxes", "backcovers", "covers", "fanart", "manuals",
    "marquees", "miximages", "physicalmedia", "screenshots",
    "titlescreens", "videos",
)

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tga"}
VIDEO_SUFFIXES = {".mp4", ".mkv", ".avi", ".webm", ".mov", ".m4v"}

MediaKind = Literal["image", "video", "pdf", "other"]


def media_kind(filename: str) -> MediaKind:
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in VIDEO_SUFFIXES:
        return "video"
    if suffix == ".pdf":
        return "pdf"
    return "other"


def rom_stem(path: str) -> str:
    """gamelist.xml の <path> 値から拡張子なしのファイル名を返す（"./a/b.chd" → "b"）。"""
    return PurePosixPath(path).stem


def validate_folder(folder: str) -> str:
    if folder not in MEDIA_FOLDERS:
        raise ValueError(f"不明なメディアフォルダです: {folder}")
    return folder


class MediaFile(BaseModel):
    folder: str
    filename: str
    size: int
    mtime: float
    kind: MediaKind


class GameMedia(BaseModel):
    path: str
    stem: str
    files: dict[str, MediaFile | None]
    """フォルダ名 → ファイル（無ければ None）。MEDIA_FOLDERS の全フォルダを含む。"""
