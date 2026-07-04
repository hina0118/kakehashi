"""kakehashiのgamelist.xmlをMCPツールとして公開するサーバー。

Steam Deck上のgamelist.xmlを外部AIエージェント（Claude等）から参照・編集できるようにする。
ツール呼び出しはセッション状態を持たず、呼び出しごとに最新のリモート内容を取得して完結させる。
"""
from mcp.server.fastmcp import FastMCP

from src.core.config_manager import load_config, discover_systems, resolve_remote_gamelist_path
from src.core.sync_manager import fetch_remote_text, push_gamelist_diff
from src.core.xml_handler import parse_gamelist_content, get_field

GAMELIST_FIELDS = ["name", "desc", "releasedate", "developer", "publisher", "genre"]

mcp = FastMCP("kakehashi")


def _sync_conn(config: dict) -> dict:
    sync_cfg = config.get("sync", {})
    return {
        "host": sync_cfg.get("host", ""),
        "port": sync_cfg.get("port", 22),
        "username": sync_cfg.get("username", "deck"),
        "password": sync_cfg.get("password", ""),
    }


def _fetch_games(system: str) -> list:
    config = load_config()
    conn = _sync_conn(config)
    if not conn["host"]:
        raise ValueError("config.jsonのsync.hostが設定されていません。")
    remote_path = resolve_remote_gamelist_path(config, system)
    content = fetch_remote_text(
        host=conn["host"], port=conn["port"],
        username=conn["username"], password=conn["password"],
        remote_path=remote_path,
    )
    _, games, _ = parse_gamelist_content(content)
    return games


@mcp.tool()
def list_systems() -> list[str]:
    """config.jsonに登録されている対象機種の一覧を返す。"""
    return discover_systems(load_config())


@mcp.tool()
def list_games(system: str) -> list[dict]:
    """指定した機種のgamelist.xmlから、各ゲームのpathとnameの一覧を取得する。"""
    games = _fetch_games(system)
    return [
        {"path": get_field(g, "path"), "name": get_field(g, "name")}
        for g in games
    ]


@mcp.tool()
def get_game(system: str, path: str) -> dict:
    """指定した機種・pathのゲームの全メタデータフィールドを取得する。"""
    games = _fetch_games(system)
    for g in games:
        if get_field(g, "path") == path:
            return {"path": path, **{f: get_field(g, f) for f in GAMELIST_FIELDS}}
    raise ValueError(f"ゲームが見つかりません: system={system}, path={path}")


@mcp.tool()
def update_game(system: str, path: str, fields: dict[str, str]) -> dict:
    """指定した機種・pathのゲームのメタデータフィールドを更新し、Steam Deckへ反映する。

    fields: 更新するタグ名と値の辞書。キーは name/desc/releasedate/developer/publisher/genre のいずれか。
    最新のリモートgamelist.xmlを取得し、指定フィールドだけを上書きして書き戻す
    （favorite/lastplayed等、kakehashiが管理しないタグには触れない）。
    """
    unknown = set(fields) - set(GAMELIST_FIELDS)
    if unknown:
        raise ValueError(f"未対応のフィールドです: {sorted(unknown)}（対応: {GAMELIST_FIELDS}）")

    config = load_config()
    conn = _sync_conn(config)
    if not conn["host"]:
        raise ValueError("config.jsonのsync.hostが設定されていません。")
    remote_path = resolve_remote_gamelist_path(config, system)

    applied, _deleted = push_gamelist_diff(
        host=conn["host"], port=conn["port"],
        username=conn["username"], password=conn["password"],
        remote_path=remote_path,
        diffs={path: fields}, deleted_paths=set(),
        backup_max=config.get("backup_max", 5),
        on_log=lambda _msg: None,
    )
    if applied == 0:
        raise ValueError(f"ゲームが見つからず更新できませんでした: system={system}, path={path}")
    return {"applied": applied}


if __name__ == "__main__":
    mcp.run(transport="stdio")
