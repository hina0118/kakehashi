from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from kakehashi.domain.works import work_url

PlayStatus = Literal["unplayed", "playing", "cleared", "completed", "onhold"]

# Steamのライブラリ画像に対応する種類（Phase 4でそのまま使う）
#   cover: 縦長カバー 600x900 / header: 横長 920x430 / hero: 背景 1920x620 / logo: 透過ロゴ / icon: アイコン
IMAGE_KINDS = ("cover", "header", "hero", "logo", "icon")
ImageKind = Literal["cover", "header", "hero", "logo", "icon"]

# 編集できるフィールド
EDITABLE_FIELDS = (
    "title", "circle", "work_id", "store", "url", "tags", "description", "release_date",
    "play_status", "rating", "notes", "local_path", "exe", "deck_dir",
    "launch_options", "compat_tool",
)


class DoujinImage(BaseModel):
    kind: ImageKind
    filename: str
    mtime: float


class DoujinGame(BaseModel):
    id: int
    title: str = ""
    circle: str = ""
    work_id: str = ""
    """販売サイトの作品ID（DLsite: RJ01234567, FANZA: d_123456 など）。"""
    store: str = ""
    url: str = ""
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    release_date: str = ""
    """YYYY-MM-DD"""
    play_status: PlayStatus = "unplayed"
    rating: int | None = None
    notes: str = ""
    local_path: str = ""
    """PC上の作品フォルダ。"""
    exe: str = ""
    """起動ファイル。作品フォルダからの相対パス（区切りは /）。"""
    deck_dir: str = ""
    """Steam Deck上の作品フォルダ。"""
    transferred_at: datetime | None = None
    launch_options: str = ""
    """Steamの起動オプション。空なら設定の既定値を使う。"""
    compat_tool: str = ""
    """Proton などの互換ツール名。空なら設定の既定値を使う。"""
    steam_appid: int | None = None
    """Steamに登録したときの appID（符号なし）。タイトルを変えても同じIDで更新するため保持し続ける。"""
    steam_registered_at: datetime | None = None
    """Steamに登録中なら登録日時、外したら None。"""
    created_at: datetime
    updated_at: datetime
    images: dict[str, DoujinImage] = Field(default_factory=dict)


class DoujinPatch(BaseModel):
    """部分更新。指定したフィールドだけを書き換える。"""
    title: str | None = None
    circle: str | None = None
    work_id: str | None = None
    store: str | None = None
    url: str | None = None
    tags: list[str] | None = None
    description: str | None = None
    release_date: str | None = None
    play_status: PlayStatus | None = None
    rating: int | None = Field(None, ge=0, le=5)
    notes: str | None = None
    local_path: str | None = None
    exe: str | None = None
    deck_dir: str | None = None
    launch_options: str | None = None
    compat_tool: str | None = None

    def changes(self) -> dict:
        # rating は None（未評価）に戻す操作もあるため、明示的に指定されたかで判定する
        return {k: getattr(self, k) for k in self.model_fields_set}


# ---- フォルダ名からの推定 ----

_WORK_ID_PATTERNS = [
    # "_" は \b では単語の一部とみなされるため、英数字との境界だけを見る（"RJ123456_タイトル" に対応）
    (re.compile(r"(?<![A-Za-z0-9])((?:RJ|RE|VJ|BJ)\d{6,8})(?!\d)", re.IGNORECASE), "dlsite"),
    (re.compile(r"(?<![A-Za-z0-9])(d_\d{5,})(?!\d)", re.IGNORECASE), "fanza"),
]
_CIRCLE_PREFIX = re.compile(r"^[\[【(（](.+?)[\]】)）]\s*(.+)$")


class FolderGuess(BaseModel):
    title: str
    circle: str = ""
    work_id: str = ""
    store: str = ""
    url: str = ""


def guess_from_folder_name(name: str) -> FolderGuess:
    """"[サークル] タイトル RJ01234567" のようなフォルダ名から作品情報を推定する。"""
    work_id = store = ""
    rest = name
    for pattern, s in _WORK_ID_PATTERNS:
        if m := pattern.search(rest):
            work_id, store = m.group(1).upper() if s == "dlsite" else m.group(1).lower(), s
            rest = (rest[:m.start()] + rest[m.end():])
            break
    rest = re.sub(r"[\s_\-]+$", "", re.sub(r"^[\s_\-]+", "", rest))
    rest = re.sub(r"[\[【(（]\s*[\]】)）]", "", rest).strip()  # IDを抜いた後の空の括弧

    circle = ""
    if m := _CIRCLE_PREFIX.match(rest):
        circle, rest = m.group(1).strip(), m.group(2).strip()
    return FolderGuess(
        title=rest or name, circle=circle, work_id=work_id, store=store, url=work_url(work_id, store),
    )


# 起動ファイルの候補から除外する名前（アンインストーラ・ランタイム・設定ツールなど）
_EXE_EXCLUDE = re.compile(
    r"unins|setup|install|crashhandler|crashpad|notification_helper|vc_?redist|dxsetup|directx|"
    r"dotnet|uninstall|updater|config|設定|nwjc|payload",
    re.IGNORECASE,
)


def rank_exe_candidates(paths: list[str]) -> list[str]:
    """作品フォルダからの相対パス一覧から、起動ファイルらしいものを優先度順に返す。"""
    cands = [
        p for p in paths
        if p.lower().endswith((".exe", ".bat")) and not _EXE_EXCLUDE.search(p.rsplit("/", 1)[-1])
    ]
    # 浅い階層を優先し、Game.exe のような定番の名前を先頭に寄せる
    def key(p: str) -> tuple:
        name = p.rsplit("/", 1)[-1].lower()
        return (p.count("/"), 0 if name in ("game.exe", "start.exe", "play.exe") else 1, p.lower())
    return sorted(cands, key=key)
