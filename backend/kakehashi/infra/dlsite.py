"""DLsiteから作品情報を取得する。

作品名・画像・登録日は作品情報API（JSON）から、サークル名とジャンルは作品ページのHTMLから取る。
"""
from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request

from pydantic import BaseModel

from kakehashi.errors import NotFoundError

_WORK_ID = re.compile(r"^(RJ|RE|VJ|BJ)\d{6,8}$")
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) kakehashi"


class DlsiteInfo(BaseModel):
    work_id: str
    title: str
    circle: str = ""
    release_date: str = ""
    """YYYY-MM-DD"""
    genres: list[str] = []
    image_url: str = ""
    url: str
    work_type: str = ""


def _get(url: str, timeout: float = 20) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA,
        # 年齢確認ページを経由せずに作品ページを取得する
        "Cookie": "adultchecked=1; locale=ja-jp",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch(work_id: str) -> DlsiteInfo:
    work_id = work_id.strip().upper()
    if not _WORK_ID.match(work_id):
        raise ValueError(f"DLsiteの作品IDではありません: {work_id}（例: RJ01234567）")

    q = urllib.parse.urlencode({"product_id": work_id, "cdn_cache_min": 1})
    data = json.loads(_get(f"https://www.dlsite.com/maniax/product/info/ajax?{q}") or "{}")
    info = data.get(work_id) if isinstance(data, dict) else None
    if not info:
        raise NotFoundError(f"DLsiteに作品が見つかりません: {work_id}")

    site = info.get("site_id") or "maniax"
    url = f"https://www.dlsite.com/{site}/work/=/product_id/{work_id}.html"
    image = info.get("work_image") or ""
    if image.startswith("//"):
        image = "https:" + image

    circle, genres = info.get("maker_name") or "", []
    try:
        page = _get(url)
        circle = circle or _parse_circle(page)
        genres = _parse_genres(page)
    except OSError:
        pass  # 作品ページが取れなくても、APIで取れた分は返す

    return DlsiteInfo(
        work_id=work_id,
        title=info.get("work_name") or "",
        circle=circle,
        release_date=(info.get("regist_date") or "")[:10],
        genres=genres,
        image_url=image,
        url=url,
        work_type=info.get("work_type") or "",
    )


def _parse_circle(page: str) -> str:
    m = re.search(r'class="maker_name"[^>]*>\s*<a[^>]*>(.*?)</a>', page, re.S)
    return html.unescape(m.group(1)).strip() if m else ""


def _parse_genres(page: str) -> list[str]:
    m = re.search(r'<div class="main_genre">(.*?)</div>', page, re.S)
    if not m:
        return []
    return [html.unescape(g).strip() for g in re.findall(r">([^<]+)</a>", m.group(1)) if g.strip()]
