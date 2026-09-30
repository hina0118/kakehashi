"""DLsiteから作品情報を取得する。

作品名・画像・登録日は作品情報API（JSON）から、サークル名とジャンルは作品ページのHTMLから取る。
"""
from __future__ import annotations

import html
import json
import math
import re
import urllib.parse
import time
import urllib.request

from kakehashi.domain.works import WorkHit, WorkInfo, work_url
from kakehashi.errors import NotFoundError

_WORK_ID = re.compile(r"^(RJ|RE|VJ|BJ)\d{6,8}$")
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) kakehashi"


def _get(url: str, timeout: float = 20) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA,
        # 年齢確認ページを経由せずに作品ページを取得する
        "Cookie": "adultchecked=1; locale=ja-jp",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch(work_id: str) -> WorkInfo:
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

    return WorkInfo(
        store="dlsite", work_id=work_id,
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


def search(keyword: str, limit: int = 30) -> list[WorkHit]:
    """タイトル・サークル名で作品を探す（DLsiteのサジェストAPI。成人向け・全年齢向けの両方が対象）。"""
    q = urllib.parse.urlencode({
        "term": keyword, "site": "adult-jp", "touch": 0, "time": int(time.time() * 1000),
    })
    data = json.loads(_get(f"https://www.dlsite.com/suggest/?{q}") or "{}")
    hits = []
    for w in (data.get("work") or [])[:limit]:
        work_id = str(w.get("workno") or "")
        if not _WORK_ID.match(work_id):
            continue
        hits.append(WorkHit(
            store="dlsite", work_id=work_id, title=str(w.get("work_name") or ""),
            circle=str(w.get("maker_name") or ""), url=work_url(work_id, "dlsite"),
            image_url=main_image_url(work_id),
            kind=_WORK_TYPES.get(str(w.get("work_type") or ""), str(w.get("work_type") or "")),
        ))
    return hits


def main_image_url(work_id: str) -> str:
    """同人作品（RJ/RE）のメイン画像のURL。画像は作品IDを千単位で切り上げたフォルダに置かれている。"""
    if not work_id[:2] in ("RJ", "RE"):
        return ""
    num = work_id[2:]
    folder = f"{work_id[:2]}{str(math.ceil(int(num) / 1000) * 1000).zfill(len(num))}"
    return f"https://img.dlsite.jp/modpub/images2/work/doujin/{folder}/{work_id}_img_main.jpg"


# DLsiteの作品形式コード（主なもの）
_WORK_TYPES = {
    "RPG": "ロールプレイング", "ACN": "アクション", "ADV": "アドベンチャー", "SLN": "シミュレーション",
    "STG": "シューティング", "PZL": "パズル", "TBL": "テーブル", "DNV": "デジタルノベル", "QIZ": "クイズ",
    "TYP": "タイピング", "ETC": "その他ゲーム", "SOU": "ボイス・ASMR", "MUS": "音楽", "MNG": "マンガ",
    "ICG": "CG・イラスト", "MOV": "動画", "NRE": "ノベル", "TOL": "ツール",
}
