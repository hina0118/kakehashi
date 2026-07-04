import json
import tkinter as tk
from pathlib import Path

CONFIG_PATH       = Path(__file__).parent.parent.parent / "config.json"
WINDOW_STATE_PATH = Path(__file__).parent.parent.parent / "window_state.json"

DEFAULT_GEOMETRY = "1100x700"

MEDIA_FOLDERS = [
    "3dboxes", "backcovers", "covers", "fanart", "manuals",
    "marquees", "miximages", "physicalmedia", "screenshots",
    "titlescreens", "videos",
]

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tga"}
VIDEO_SUFFIXES = {".mp4", ".mkv", ".avi", ".webm", ".mov", ".m4v"}

THUMB_W, THUMB_H = 96, 72  # メディアタブのサムネイルサイズ


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_window_state() -> str:
    try:
        with open(WINDOW_STATE_PATH, encoding="utf-8") as f:
            return json.load(f).get("geometry", DEFAULT_GEOMETRY)
    except FileNotFoundError:
        return DEFAULT_GEOMETRY


def save_window_state(root: tk.Tk) -> None:
    with open(WINDOW_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"geometry": root.geometry()}, f, indent=2)


def discover_systems(config: dict) -> list[str]:
    """ローカル(Windows)の rom_base 配下のフォルダ名からシステム一覧を取得する。
    フォルダが見つからない場合は config.json の systems にフォールバックする。
    """
    base = config.get("windows", {}).get("rom_base", "")
    if base:
        p = Path(base)
        if p.is_dir():
            dirs = sorted(d.name for d in p.iterdir() if d.is_dir())
            if dirs:
                return dirs
    return config.get("systems", [])


def resolve_paths(config: dict, system: str) -> dict:
    """ローカル(Windows)側のROM・メディアパスを解決する。"""
    base = config.get("windows", {})
    return {
        "rom_path":   str(Path(base.get("rom_base",   "")) / system),
        "media_path": str(Path(base.get("media_base", "")) / system),
    }


def resolve_remote_gamelist_path(config: dict, system: str) -> str:
    """Steam Deck上のgamelist.xmlのリモートパスを組み立てる。"""
    base = config.get("steam_deck", {}).get(
        "gamelist_base", "/home/deck/.emulationstation/gamelists"
    )
    return f"{base}/{system}/gamelist.xml"
