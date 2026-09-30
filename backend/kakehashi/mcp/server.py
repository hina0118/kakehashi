"""kakehashi のサービスを MCP ツールとして公開する。

Web UI と同じ services を呼ぶだけの薄い層。ツール呼び出しごとに Deck から最新の
gamelist.xml を取得し直す（UI 側で編集中の内容と食い違わないようにするため）。
"""
from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from kakehashi.context import AppContext
from kakehashi.domain.doujin import DoujinPatch
from kakehashi.domain.esde import EDITABLE_FIELDS, GameUpdate
from kakehashi.domain.media import rom_stem

mcp = FastMCP("kakehashi")
_ctx = AppContext()


@mcp.tool()
def list_systems() -> list[str]:
    """config.json に設定されている機種（ES-DE のシステム名）の一覧を返す。"""
    return _ctx.esde.list_systems()


@mcp.tool()
def list_games(system: str, include_new_roms: bool = False) -> list[dict]:
    """指定した機種の gamelist.xml から、各ゲームの path と name の一覧を取得する。

    include_new_roms: True にすると、Deck の ROM フォルダにあって gamelist.xml に未登録の
    ファイルも返す（registered: false、name は空）。登録するには update_games を呼ぶ。
    """
    games = list(_ctx.esde.get_games(system, refresh=True))
    if include_new_roms:
        games += _ctx.esde.find_unregistered_roms(system)
    return [{"path": g.path, "name": g.name, "registered": g.registered} for g in games]


@mcp.tool()
def get_games(system: str, paths: list[str] | None = None) -> list[dict]:
    """指定した機種のゲームのメタデータをまとめて取得する。paths 省略時は全件。"""
    games = _ctx.esde.get_games(system, refresh=True)
    if paths is not None:
        wanted = set(paths)
        games = [g for g in games if g.path in wanted]
    return [g.model_dump(include={"path", *EDITABLE_FIELDS}) for g in games]


@mcp.tool()
def update_games(system: str, updates: list[dict]) -> dict:
    """複数ゲームのメタデータをまとめて更新し、1 回の書き込みで Deck へ反映する。

    updates: [{"path": "./game.zip", "fields": {"name": "...", ...}}, ...]
    fields のキーは name/desc/releasedate/developer/publisher/genre のいずれか。
    releasedate は YYYYMMDDT000000 形式。指定したタグ以外（favorite 等）には触れない。
    """
    result = _ctx.esde.update_games(system, [GameUpdate.model_validate(u) for u in updates])
    return {"applied": result.applied, "requested": result.requested}


@mcp.tool()
def check_videos(system: str, paths: list[str] | None = None) -> list[dict]:
    """指定した機種のゲームについて、PC側にプレイ動画（videos）があるかをまとめて確認する。

    paths: 確認対象の path のリスト。省略時は機種内の全ゲーム。
    見るのはPC側の media_base フォルダで、Deck への反映は Web UI の「Deckへプッシュ」で行う。
    戻り値: [{"path", "name", "has_video", "video_file"}, ...]
    """
    games = _ctx.esde.get_games(system, refresh=True)
    if paths is not None:
        wanted = set(paths)
        games = [g for g in games if g.path in wanted]
    coverage = _ctx.media.coverage(system)
    result = []
    for g in games:
        video = coverage.get(rom_stem(g.path), {}).get("videos")
        result.append({"path": g.path, "name": g.name, "has_video": video is not None, "video_file": video})
    return result


@mcp.tool()
def update_videos(system: str, updates: list[dict]) -> dict:
    """複数ゲームのプレイ動画をまとめて登録・置換・削除する（保存先はPC側）。

    updates: [{"path": "./game.zip", "source": "http(s)://... またはローカルファイルパス"}, ...]
    source が http(s):// なら yt-dlp で取得する（動画ページURL・動画ファイルへの直リンクの両方に対応）。
    それ以外はローカルファイルとしてコピーする。source を省略/空にすると既存の動画を削除する。
    戻り値: {"applied", "requested", "errors": [{"path", "error"}, ...]}
    """
    applied, errors = 0, []
    for item in updates:
        path, source = item["path"], (item.get("source") or "").strip()
        try:
            if not source:
                _ctx.media.delete(system, path, "videos")
            elif source.startswith(("http://", "https://")):
                _ctx.media.import_url(system, path, "videos", source)
            else:
                _ctx.media.import_file(system, path, "videos", Path(source))
            applied += 1
        except Exception as e:
            errors.append({"path": path, "error": str(e)})
    return {"applied": applied, "requested": len(updates), "errors": errors}


_DOUJIN_SUMMARY = ("id", "title", "circle", "work_id", "play_status", "tags")


@mcp.tool()
def list_doujin(query: str = "") -> list[dict]:
    """同人ゲーム台帳の一覧（id, title, circle, work_id, play_status, tags）を返す。

    query: タイトル・サークル・作品ID・タグの部分一致で絞り込む（大文字小文字は区別しない）。
    """
    q = query.strip().lower()
    games = _ctx.doujin.list()
    if q:
        games = [
            g for g in games
            if q in " ".join([g.title, g.circle, g.work_id, *g.tags]).lower()
        ]
    return [g.model_dump(include=set(_DOUJIN_SUMMARY)) for g in games]


@mcp.tool()
def get_doujin(ids: list[int]) -> list[dict]:
    """同人ゲームの全項目をまとめて取得する。"""
    return [_ctx.doujin.get(i).model_dump(mode="json", exclude={"images"}) for i in ids]


@mcp.tool()
def update_doujin(updates: list[dict]) -> dict:
    """同人ゲームのメタデータをまとめて更新する。

    updates: [{"id": 1, "fields": {"title": "...", "tags": ["RPG"], ...}}, ...]
    fields のキー: title, circle, work_id, store, url, tags(文字列の配列), description,
    release_date(YYYY-MM-DD), play_status(unplayed/playing/cleared/completed/onhold),
    rating(0-5 または null), notes, exe(作品フォルダからの相対パス)
    戻り値: {"applied", "requested", "errors": [{"id", "error"}, ...]}
    """
    applied, errors = 0, []
    for item in updates:
        try:
            _ctx.doujin.update(int(item["id"]), DoujinPatch.model_validate(item["fields"]))
            applied += 1
        except Exception as e:
            errors.append({"id": item.get("id"), "error": str(e)})
    return {"applied": applied, "requested": len(updates), "errors": errors}


@mcp.tool()
def fetch_work(store: str, work_id: str) -> dict:
    """販売サイトの作品IDから、タイトル・サークル・発売日・ジャンル・画像URLを取得する。

    store: dlsite（RJ01234567 など） / fanza（FANZA同人。d_123456） /
           fanza_games（FANZA GAMES のPCゲーム。aman_0937 など） / dmm_games（DMM GAMES のPCゲーム）
    """
    return _ctx.doujin.fetch_work(store, work_id).model_dump()


@mcp.tool()
def search_works(keyword: str, stores: list[str] | None = None) -> dict:
    """タイトルやサークル名で販売サイトを検索し、作品IDの候補を返す。

    stores: 検索するサイト（dlsite / fanza / fanza_games / dmm_games）。省略時はすべて。
    戻り値: {"hits": [{"store", "work_id", "title", "circle", "kind", "url"}, ...], "errors": {サイト: エラー}}
    台帳の作品に work_id と store を設定するには update_doujin を使う。
    """
    return _ctx.doujin.search_works(keyword, stores).model_dump()


def run() -> None:
    mcp.run(transport="stdio")
