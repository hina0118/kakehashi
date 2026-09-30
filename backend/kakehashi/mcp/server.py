"""kakehashi のサービスを MCP ツールとして公開する。

Web UI と同じ services を呼ぶだけの薄い層。ツール呼び出しごとに Deck から最新の
gamelist.xml を取得し直す（UI 側で編集中の内容と食い違わないようにするため）。
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from kakehashi.context import AppContext
from kakehashi.domain.esde import EDITABLE_FIELDS, GameUpdate

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


def run() -> None:
    mcp.run(transport="stdio")
