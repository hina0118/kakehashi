"""DMM の作品情報の取得とタイトル検索（FANZA同人 / FANZA GAMES / DMM GAMES）。

公式APIは利用登録が必要なため、作品ページと検索結果ページのHTMLから読み取る。
ページの構成が変わると取得できなくなるので、読み取りに失敗したら分かるエラーを出す。
"""
from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request

from kakehashi.domain.works import WorkHit, WorkInfo, work_url
from kakehashi.errors import NotFoundError

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) kakehashi"
# 年齢確認・地域確認のページを経由せずに取得する
_COOKIE = "age_check_done=1; ckcy=1; cklg=ja"

_DOUJIN_ID = re.compile(r"^d_\d+$")
_PCGAME_ID = re.compile(r"^[a-z0-9]+_[a-z0-9]+$")
# 作品名の先頭に付く区分（【ゲーム】など）
_CATEGORY_PREFIX = re.compile(r"^【[^】]{1,12}】\s*")

# ジャンル欄に混ざるセール・キャンペーンのタグ
_PROMOTION = re.compile(r"OFF|キャンペーン|クーポン|還元|対象|セール|割引|ポイント")

_PCGAME_HOSTS = {"fanza_games": "dlsoft.dmm.co.jp", "dmm_games": "dlsoft.dmm.com"}


def _get(url: str, timeout: float = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Cookie": _COOKIE, "Accept-Language": "ja"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise NotFoundError(f"作品ページが見つかりません: {url}") from e
        raise


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _json_ld(page: str) -> list[dict]:
    out = []
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue  # 壊れたJSON-LD（改行を含む文字列など）は飛ばす
        out.extend(data if isinstance(data, list) else [data])
    return out


def _date(value: str) -> str:
    m = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", value)
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""


# ---- FANZA同人 ----

def fetch_doujin(work_id: str) -> WorkInfo:
    work_id = work_id.strip().lower()
    if not _DOUJIN_ID.match(work_id):
        raise ValueError(f"FANZA同人の作品IDではありません: {work_id}（例: d_123456）")
    url = work_url(work_id, "fanza")
    page = _get(url)
    product = next((d for d in _json_ld(page) if d.get("@type") == "Product"), None)
    if product is None:
        raise ValueError("FANZAの作品ページを読み取れませんでした（ページの構成が変わった可能性があります）。")

    images = product.get("image") or []
    image = images[0] if isinstance(images, list) and images else (images if isinstance(images, str) else "")
    brand = product.get("brand") or {}
    date = ""
    if m := re.search(r"配信開始日</dt>\s*<dd[^>]*>(.*?)</dd>", page, re.S):
        date = _date(_text(m.group(1)))
    genres = [html.unescape(g).strip() for g in re.findall(r'genreTag__txt[^>]*>([^<]+)<', page)]
    kind = ""
    if m := re.search(r"作品形式</dt>\s*<dd[^>]*>(.*?)</dd>", page, re.S):
        kind = _text(m.group(1))
    return WorkInfo(
        store="fanza", work_id=work_id,
        title=_CATEGORY_PREFIX.sub("", str(product.get("name") or "")).strip(),
        circle=str(brand.get("name") or "") if isinstance(brand, dict) else "",
        release_date=date, genres=[g for g in genres if g], image_url=image, url=url, work_type=kind,
    )


def search_doujin(keyword: str, limit: int = 30) -> list[WorkHit]:
    url = f"https://www.dmm.co.jp/dc/doujin/-/list/narrow/=/word={urllib.parse.quote(keyword)}/"
    page = _get(url)
    hits = []
    for item in re.findall(r'<li class="productList__item">(.*?)</li>\s*(?=<li class="productList__item">|</ul>)', page, re.S):
        m = re.search(r'cid=(d_\d+)/', item)
        if not m:
            continue
        img = re.search(r'<img\s+src="([^"]+)"', item)
        title = re.search(r'class="tileListTtl__txt">\s*<a[^>]*>(.*?)</a>', item, re.S)
        kind = re.search(r'class="c_icon_genre">([^<]+)<', item)
        circle = re.search(r'class="tileListTtl__txt--author"[^>]*>(.*?)</div>', item, re.S)
        hits.append(WorkHit(
            store="fanza", work_id=m.group(1),
            title=_text(title.group(1)) if title else "",
            circle=_text(circle.group(1)) if circle else "",
            image_url=img.group(1) if img else "",
            url=work_url(m.group(1), "fanza"), kind=kind.group(1).strip() if kind else "",
        ))
        if len(hits) >= limit:
            break
    return hits


# ---- FANZA GAMES / DMM GAMES（PCゲーム） ----

def fetch_pcgame(work_id: str, store: str) -> WorkInfo:
    work_id = work_id.strip().lower()
    if store not in _PCGAME_HOSTS:
        raise ValueError(f"PCゲームの販売サイトではありません: {store}")
    if not _PCGAME_ID.match(work_id):
        raise ValueError(f"作品IDの形式が正しくありません: {work_id}（例: aman_0937）")
    url = work_url(work_id, store)
    page = _get(url)
    lds = _json_ld(page)
    product = next((d for d in lds if d.get("@type") == "Product"), None)
    if product is None:
        raise ValueError("作品ページを読み取れませんでした（ページの構成が変わった可能性があります）。")

    # ブランド名はパンくずリストの2番目（トップ > ブランド > 作品）
    circle = ""
    crumbs = next((d for d in lds if d.get("@type") == "BreadcrumbList"), None)
    if crumbs:
        items = crumbs.get("itemListElement") or []
        if len(items) >= 3:
            circle = str(items[1].get("name") or "")

    table = _detail_table(page)
    date = next((_date(v[0]) for k, v in table.items() if "配信開始日" in k and v), "")
    genres = [g for g in table.get("ジャンル", []) if not _PROMOTION.search(g)]
    image = product.get("image") or ""
    return WorkInfo(
        store=store, work_id=work_id, title=str(product.get("name") or "").strip(), circle=circle,
        release_date=date, genres=genres,
        image_url=image[0] if isinstance(image, list) and image else str(image), url=url,
    )


def _detail_table(page: str) -> dict[str, list[str]]:
    """作品ページ下部の表を {見出し: [値, ...]} にする。"""
    out: dict[str, list[str]] = {}
    rows = re.split(r'<div class="contentsDetailBottom__tableRow[^"]*">', page)[1:]
    for row in rows:
        label = re.search(r'contentsDetailBottom__tableDataLeft">\s*<p>(.*?)</p>', row, re.S)
        if not label:
            continue
        right = row.split("contentsDetailBottom__tableDataRight", 1)[-1]
        # 値はリスト（ul）か、最初の span の中だけから取る（行の外のリンクを拾わない）
        if (ul := re.search(r"<ul[^>]*>(.*?)</ul>", right, re.S)) and right.find("<ul") < right.find("</div>"):
            values = [_text(v) for v in re.findall(r"<li[^>]*>(.*?)</li>", ul.group(1), re.S)]
        elif span := re.search(r"<span[^>]*>(.*?)</span>", right, re.S):
            values = [_text(span.group(1))]
        else:
            values = []
        out[_text(label.group(1))] = [v for v in values if v]
    return out


def search_pcgame(keyword: str, store: str, limit: int = 30) -> list[WorkHit]:
    host = _PCGAME_HOSTS[store]
    q = urllib.parse.quote(keyword)
    if store == "fanza_games":
        url = f"https://{host}/search/?service=pcgame&searchstr={q}"
    else:
        url = f"https://{host}/search?service=pcsoft&floor=digital_pcgame&searchstr={q}"
    page = _get(url)
    hits = []
    for m in re.finditer(
        r'class="productListItem".*?href="https://' + re.escape(host) + r'/detail/([a-z0-9_]+)/" title="([^"]+)"'
        r'.*?<img src="([^"]+)"', page, re.S,
    ):
        hits.append(WorkHit(
            store=store, work_id=m.group(1), title=html.unescape(m.group(2)),
            image_url=m.group(3), url=work_url(m.group(1), store), kind="PCゲーム",
        ))
        if len(hits) >= limit:
            break
    return hits
