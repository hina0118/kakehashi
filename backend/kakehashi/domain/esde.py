from __future__ import annotations

from pydantic import BaseModel, Field

# kakehashiから編集できるgamelist.xmlのタグ。これ以外のタグは読み取り専用で保持する。
EDITABLE_FIELDS = ("name", "desc", "releasedate", "developer", "publisher", "genre")


class EsdeGame(BaseModel):
    path: str
    name: str = ""
    desc: str = ""
    releasedate: str = ""
    developer: str = ""
    publisher: str = ""
    genre: str = ""
    registered: bool = True
    """False は Deck のROMフォルダにあるが gamelist.xml に未登録のファイル。"""
    extra: dict[str, str] = Field(default_factory=dict)
    """編集対象外のタグ（favorite, playcount など）。"""


class GameUpdate(BaseModel):
    path: str
    fields: dict[str, str]


class UpdateResult(BaseModel):
    applied: int
    deleted: int = 0
    requested: int
