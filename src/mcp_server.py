"""kakehashiのgamelist.xmlをMCPツールとして公開するサーバー。

Steam Deck上のgamelist.xmlを外部AIエージェント（Claude等）から参照・編集できるようにする。
ツール呼び出しはセッション状態を持たず、呼び出しごとに最新のリモート内容を取得して完結させる。
"""
import shutil
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from src.core.config_manager import (
    load_config, discover_systems, resolve_remote_gamelist_path, resolve_paths,
)
from src.core.sync_manager import fetch_remote_text, push_gamelist_diff
from src.core.xml_handler import parse_gamelist_content, get_field
from src.media.processor import get_rom_stem, download_video_via_ytdlp

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
def get_games(system: str, paths: list[str] | None = None) -> list[dict]:
    """指定した機種のゲームの全メタデータフィールドをまとめて取得する。

    paths: 取得対象のpathのリスト。省略時は機種内の全ゲームを返す。
    リモートgamelist.xmlの取得は呼び出し1回につき1回だけ行うため、
    複数ゲームをまとめて確認したい場合は1件ずつget_gamesを呼ぶより高速。
    """
    games = _fetch_games(system)
    if paths is not None:
        path_set = set(paths)
        games = [g for g in games if get_field(g, "path") in path_set]
    return [
        {"path": get_field(g, "path"), **{f: get_field(g, f) for f in GAMELIST_FIELDS}}
        for g in games
    ]


@mcp.tool()
def update_games(system: str, updates: list[dict]) -> dict:
    """複数ゲームのメタデータをまとめて更新し、1回のリモート書き込みでSteam Deckへ反映する。

    updates: [{"path": "./game.zip", "fields": {"name": "...", ...}}, ...] の形式のリスト。
    fieldsのキーは name/desc/releasedate/developer/publisher/genre のいずれか。
    最新のリモートgamelist.xmlを1回取得し、指定した各pathのフィールドだけを上書きして
    まとめて書き戻す（favorite/lastplayed等、kakehashiが管理しないタグには触れない）。
    1件ずつupdate_gamesを呼ぶより高速。

    戻り値: {"applied": 実際に反映できた件数, "requested": 要求件数}
    """
    diffs: dict[str, dict[str, str]] = {}
    for item in updates:
        path = item["path"]
        fields = item["fields"]
        unknown = set(fields) - set(GAMELIST_FIELDS)
        if unknown:
            raise ValueError(f"未対応のフィールドです（path={path}）: {sorted(unknown)}（対応: {GAMELIST_FIELDS}）")
        diffs[path] = fields

    if not diffs:
        return {"applied": 0, "requested": 0}

    config = load_config()
    conn = _sync_conn(config)
    if not conn["host"]:
        raise ValueError("config.jsonのsync.hostが設定されていません。")
    remote_path = resolve_remote_gamelist_path(config, system)

    applied, _deleted = push_gamelist_diff(
        host=conn["host"], port=conn["port"],
        username=conn["username"], password=conn["password"],
        remote_path=remote_path,
        diffs=diffs, deleted_paths=set(),
        backup_max=config.get("backup_max", 5),
        on_log=lambda _msg: None,
    )
    return {"applied": applied, "requested": len(diffs)}


def _videos_dir(config: dict, system: str) -> Path:
    return Path(resolve_paths(config, system)["media_path"]) / "videos"


@mcp.tool()
def check_videos(system: str, paths: list[str] | None = None) -> list[dict]:
    """指定した機種のゲームについて、ローカル(Windows)側にvideo(プレイ動画)ファイルが
    登録済みかどうかをまとめて確認する。

    paths: 確認対象のpathのリスト。省略時は機種内の全ゲームを対象にする。
    ここで見るのはローカルのmedia_baseフォルダであり、Steam Deck上の実体ではない
    （ローカルとSteam Deckの反映は別途「同期」操作で行う）。

    戻り値: [{"path": ..., "name": ..., "has_video": bool, "video_file": ファイル名 or None}, ...]
    """
    games = _fetch_games(system)
    if paths is not None:
        path_set = set(paths)
        games = [g for g in games if get_field(g, "path") in path_set]

    videos_dir = _videos_dir(load_config(), system)

    result = []
    for g in games:
        path_val = get_field(g, "path")
        stem = get_rom_stem(path_val) if path_val else ""
        matches = list(videos_dir.glob(f"{stem}.*")) if stem and videos_dir.is_dir() else []
        result.append({
            "path": path_val,
            "name": get_field(g, "name"),
            "has_video": bool(matches),
            "video_file": matches[0].name if matches else None,
        })
    return result


@mcp.tool()
def update_videos(system: str, updates: list[dict]) -> dict:
    """複数ゲームのvideoファイルをまとめて登録・置換・削除する。

    updates: [{"path": "./game.zip", "source": "http(s)://... またはローカルファイルパス"}, ...]
    sourceがhttp(s)://で始まる場合はyt-dlpでダウンロードして登録する
    （YouTube等の動画ページURL、および動画ファイル本体への直リンクの両方に対応）。
    それ以外はローカルファイルパスと見なしてコピーする。
    sourceを省略/空文字にすると既存のvideoファイルを削除する。
    保存先はローカル(Windows)のmedia_baseフォルダのみで、Steam Deckへの反映には別途
    「同期」操作が必要。

    戻り値: {"applied": 反映件数, "requested": 要求件数, "errors": [{"path": ..., "error": ...}, ...]}
    """
    videos_dir = _videos_dir(load_config(), system)

    applied = 0
    errors: list[dict] = []
    for item in updates:
        path_val = item["path"]
        source = (item.get("source") or "").strip()
        stem = get_rom_stem(path_val)
        try:
            existing = list(videos_dir.glob(f"{stem}.*")) if videos_dir.is_dir() else []

            if not source:
                for f in existing:
                    f.unlink()
                applied += 1
                continue

            if source.startswith("http://") or source.startswith("https://"):
                dest = download_video_via_ytdlp(source, videos_dir, stem)
                for f in existing:
                    if f != dest:
                        f.unlink()
            else:
                src_path = Path(source)
                if not src_path.is_file():
                    raise ValueError(f"ファイルが見つかりません: {source}")
                dest = videos_dir / f"{stem}{src_path.suffix.lower()}"
                videos_dir.mkdir(parents=True, exist_ok=True)
                for f in existing:
                    if f != dest:
                        f.unlink()
                shutil.copy2(src_path, dest)

            applied += 1
        except Exception as e:
            errors.append({"path": path_val, "error": str(e)})

    return {"applied": applied, "requested": len(updates), "errors": errors}


if __name__ == "__main__":
    mcp.run(transport="stdio")
