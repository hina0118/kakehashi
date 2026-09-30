"""URLからメディアファイルを取得する。"""
from __future__ import annotations

import mimetypes
import urllib.parse
import urllib.request
from pathlib import Path

from kakehashi.domain.media import IMAGE_SUFFIXES, VIDEO_SUFFIXES

_KNOWN_SUFFIXES = IMAGE_SUFFIXES | VIDEO_SUFFIXES | {".pdf"}


def ytdlp_available() -> bool:
    try:
        import yt_dlp  # noqa: F401
        return True
    except ImportError:
        return False


def download_with_ytdlp(url: str, dest_dir: Path, stem: str) -> Path:
    """YouTube等の動画ページ、または動画ファイルへの直リンクを取得する。

    ffmpegによる音声/映像の結合を要しない単一ファイル形式だけを対象にする。
    """
    import yt_dlp

    dest_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "outtmpl": str(dest_dir / f"{stem}.%(ext)s"),
        "format": "best[ext=mp4]/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logtostderr": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        result = Path(ydl.prepare_filename(info))

    if result.suffix.lower() not in VIDEO_SUFFIXES:
        result.unlink(missing_ok=True)
        raise ValueError(f"動画として取得できませんでした（拡張子: {result.suffix or '不明'}）。")
    return result


def download_file(url: str, timeout: float = 30) -> tuple[bytes, str]:
    """URLの内容と拡張子を返す。拡張子はURLのパス、無ければContent-Typeから決める。"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content_type = resp.headers.get("Content-Type", "").split(";")[0].strip()
        data = resp.read()

    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if suffix not in _KNOWN_SUFFIXES:
        suffix = mimetypes.guess_extension(content_type) or ""
        if suffix in (".jpe", ".jpeg"):
            suffix = ".jpg"
    if suffix not in _KNOWN_SUFFIXES:
        raise ValueError(f"ファイル形式を判定できませんでした（Content-Type: {content_type or '不明'}）。")
    return data, suffix
