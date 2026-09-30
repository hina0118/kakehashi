"""販売サイト（DLsite / FANZA同人 / FANZA GAMES / DMM GAMES）の読み取り。実ページの構造を模したHTMLで確かめる。"""
import json

import pytest

from kakehashi.infra import dlsite, dmm

FANZA_DETAIL = """
<script type="application/ld+json">{"@context":"http://schema.org","@type":"Product",
"name":"【ゲーム】あの日の作品","image":["https://doujin-assets.dmm.co.jp/digital/game/d_580141/d_580141pr.jpg"],
"brand":{"@type":"Brand","name":"サークルX"},"sku":"d_580141"}</script>
<script type="application/ld+json">{"broken": </script>
<dl class="informationList"><dt class="informationList__ttl">配信開始日</dt>
<dd class="informationList__txt">2026/09/16 00:00</dd></dl>
<dl class="informationList"><dt class="informationList__ttl">作品形式</dt><dd class="informationList__txt"><a href="#">ゲーム</a></dd></dl>
<li><a class="genreTag__txt" href="#">制服</a></li><li><a class="genreTag__txt" href="#">シミュレーション</a></li>
"""

FANZA_SEARCH = """
<ul class="productList fn-productList">
<li class="productList__item"> <div class="tileListImg__tmb "> <a href="https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_319834/">
<img src="https://doujin-assets.dmm.co.jp/digital/game/d_319834/d_319834pl.jpg"
 alt="ダンジョンタウン完全版"> </a> </div>
<div class="c_icon_genre">ゲーム</div>
<div class="tileListTtl__txt"> <a href="https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_319834/"> ダンジョンタウン完全版 </a> </div>
<div class="tileListTtl__txt--author"> <a href="#"> サークル冥魅亭 </a>
   /  <a href="#">声優</a> </div>
<ul class="productTable-purchaseStatusList"><li>クーポンあり</li></ul>
</li>
<li class="productList__item"> <a href="https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_320011/"><img src="x.jpg" alt="IF"></a>
<div class="c_icon_genre">ボイス</div><div class="tileListTtl__txt"><a href="#">IFストーリー</a></div>
</li>
</ul>
"""

PCGAME_DETAIL = """
<script type="application/ld+json">{"@type":"BreadcrumbList","itemListElement":[
{"@type":"ListItem","position":1,"name":"アダルトPCゲームトップ"},{"@type":"ListItem","position":2,"name":"SURVIVE MORE"},
{"@type":"ListItem","position":3,"name":"殲光のイクス"}]}</script>
<script type="application/ld+json">{"@type":"Product","name":"殲光のイクス","image":"https://pics.dmm.co.jp/digital/pcgame/aman_0937/aman_0937pl.jpg"}</script>
<div class="contentsDetailBottom__table">
<div class="contentsDetailBottom__tableRow"> <div class="contentsDetailBottom__tableDataLeft"> <p>ダウンロード版配信開始日</p> </div>
 <div class="contentsDetailBottom__tableDataRight"> <div> <span>2025/07/04 00:00</span> </div> </div> </div>
<div class="contentsDetailBottom__tableRow contentsDetailBottom__tableRow--container"> <div class="contentsDetailBottom__tableDataLeft"> <p>ジャンル</p> </div>
 <div class="contentsDetailBottom__tableDataRight"> <ul class="contentsDetailBottom__tableDataList">
 <li class="contentsDetailBottom__tableDataItem"><a href="#">SF</a></li>
 <li class="contentsDetailBottom__tableDataItem"><a href="#">50%OFF！ 秋のキャンペーン</a></li>
 <li class="contentsDetailBottom__tableDataItem"><a href="#">触手</a></li></ul> </div> </div>
</div>
<footer><a href="#">会社概要</a></footer>
"""

PCGAME_SEARCH = """
<li class="productListItem"> <div> <a href="https://dlsoft.dmm.com/detail/clear_0036/" title="9-nine- 新章" class="x">
<div><img src="https://pics.dmm.com/digital/pcgame/clear_0036/clear_0036pl.jpg" alt="x"></div></a></div></li>
<a class="component-floorMenu__listLink" href="https://dlsoft.dmm.com/detail/nav_0001/">ナビ</a>
"""


def test_fanza_doujin_detail(monkeypatch):
    monkeypatch.setattr(dmm, "_get", lambda url, timeout=20: FANZA_DETAIL)
    info = dmm.fetch_doujin("D_580141")
    assert (info.store, info.work_id, info.title, info.circle, info.release_date, info.work_type) == (
        "fanza", "d_580141", "あの日の作品", "サークルX", "2026-09-16", "ゲーム",
    )
    assert info.genres == ["制服", "シミュレーション"]
    assert info.image_url.endswith("d_580141pr.jpg")
    with pytest.raises(ValueError):
        dmm.fetch_doujin("RJ123456")


def test_fanza_doujin_search(monkeypatch):
    monkeypatch.setattr(dmm, "_get", lambda url, timeout=20: FANZA_SEARCH)
    hits = dmm.search_doujin("ダンジョンタウン")
    assert [(h.work_id, h.title, h.kind) for h in hits] == [
        ("d_319834", "ダンジョンタウン完全版", "ゲーム"), ("d_320011", "IFストーリー", "ボイス"),
    ]
    assert hits[0].circle.startswith("サークル冥魅亭")
    assert hits[0].image_url.endswith("d_319834pl.jpg")


def test_pcgame_detail_filters_promotions(monkeypatch):
    monkeypatch.setattr(dmm, "_get", lambda url, timeout=20: PCGAME_DETAIL)
    info = dmm.fetch_pcgame("aman_0937", "fanza_games")
    assert (info.title, info.circle, info.release_date, info.genres) == ("殲光のイクス", "SURVIVE MORE", "2025-07-04", ["SF", "触手"])
    assert info.url == "https://dlsoft.dmm.co.jp/detail/aman_0937/"
    assert dmm.fetch_pcgame("aman_0937", "dmm_games").url.startswith("https://dlsoft.dmm.com/")


def test_pcgame_search_ignores_navigation_links(monkeypatch):
    monkeypatch.setattr(dmm, "_get", lambda url, timeout=20: PCGAME_SEARCH)
    hits = dmm.search_pcgame("9-nine", "dmm_games")
    assert [(h.work_id, h.title, h.store) for h in hits] == [("clear_0036", "9-nine- 新章", "dmm_games")]


def test_dlsite_search(monkeypatch):
    data = {"work": [
        {"workno": "RJ431925", "work_name": "ハチナ怪異譚", "maker_name": "八角家", "work_type": "ACN"},
        {"workno": "broken"},
    ]}
    monkeypatch.setattr(dlsite, "_get", lambda url, timeout=20: json.dumps(data))
    [hit] = dlsite.search("ハチナ")
    assert (hit.work_id, hit.title, hit.circle, hit.kind) == ("RJ431925", "ハチナ怪異譚", "八角家", "アクション")
    assert hit.image_url == "https://img.dlsite.jp/modpub/images2/work/doujin/RJ432000/RJ431925_img_main.jpg"
    assert dlsite.main_image_url("RJ01014447").endswith("/RJ01015000/RJ01014447_img_main.jpg")
    assert dlsite.main_image_url("BJ123456") == ""


def test_search_works_reports_errors_per_store(ctx, monkeypatch):
    monkeypatch.setattr(dlsite, "search", lambda kw: [])
    monkeypatch.setattr(dmm, "search_doujin", lambda kw: (_ for _ in ()).throw(OSError("timeout")))
    monkeypatch.setattr(dmm, "search_pcgame", lambda kw, store: [])
    result = ctx.doujin.search_works("x")
    assert result.hits == [] and set(result.errors) == {"fanza"}
    with pytest.raises(ValueError):
        ctx.doujin.search_works("  ")
    assert ctx.doujin.search_works("x", ["dlsite"]).errors == {}


def test_fetch_work_dispatches_by_store(ctx, monkeypatch):
    monkeypatch.setattr(dmm, "_get", lambda url, timeout=20: PCGAME_DETAIL)
    assert ctx.doujin.fetch_work("dmm_games", "clear_0047").store == "dmm_games"
    with pytest.raises(ValueError):
        ctx.doujin.fetch_work("booth", "123")
