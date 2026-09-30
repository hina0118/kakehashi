"""販売サイト（DLsite / FANZA同人 / FANZA GAMES / DMM GAMES）の作品情報。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

StoreId = Literal["dlsite", "fanza", "fanza_games", "dmm_games"]

STORE_LABELS: dict[str, str] = {
    "dlsite": "DLsite",
    "fanza": "FANZA同人",
    "fanza_games": "FANZA GAMES",
    "dmm_games": "DMM GAMES",
}


class WorkInfo(BaseModel):
    """作品ページから取得した情報。"""
    store: StoreId
    work_id: str
    title: str
    circle: str = ""
    """サークル・ブランド・メーカー"""
    release_date: str = ""
    """YYYY-MM-DD"""
    genres: list[str] = []
    image_url: str = ""
    url: str
    work_type: str = ""


class WorkHit(BaseModel):
    """タイトル検索の候補。"""
    store: StoreId
    work_id: str
    title: str
    circle: str = ""
    image_url: str = ""
    url: str
    kind: str = ""
    """作品の区分（ゲーム・音声・コミックなど、サイトが示すもの）"""


def work_url(work_id: str, store: str) -> str:
    if not work_id:
        return ""
    if store == "dlsite":
        return f"https://www.dlsite.com/maniax/work/=/product_id/{work_id}.html"
    if store == "fanza":
        return f"https://www.dmm.co.jp/dc/doujin/-/detail/=/cid={work_id}/"
    if store == "fanza_games":
        return f"https://dlsoft.dmm.co.jp/detail/{work_id}/"
    if store == "dmm_games":
        return f"https://dlsoft.dmm.com/detail/{work_id}/"
    return ""
