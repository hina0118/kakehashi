"""kakehashi のサービスを MCP ツールとして公開する。

Web UI と同じ services を呼ぶだけの薄い層。ツール呼び出しごとに Deck から最新の
gamelist.xml を取得し直す（UI 側で編集中の内容と食い違わないようにするため）。
"""
from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from kakehashi.context import AppContext
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


def run() -> None:
    mcp.run(transport="stdio")
