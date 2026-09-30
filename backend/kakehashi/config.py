"""config.json の読み書き。

旧tkinterアプリと同じファイル・同じキー構成を使う。kakehashiが知らないキーも
保存時に失われないよう、各モデルは extra="allow" にしている。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.json"


def config_path() -> Path:
    env = os.environ.get("KAKEHASHI_CONFIG_PATH")
    return Path(env) if env else _DEFAULT_CONFIG_PATH


def data_dir() -> Path:
    """kakehashiが作業データ（未反映の削除、同人台帳など）を置くフォルダ。"""
    env = os.environ.get("KAKEHASHI_DATA_DIR")
    d = Path(env) if env else PROJECT_ROOT / "work"
    d.mkdir(parents=True, exist_ok=True)
    return d


class _Section(BaseModel):
    model_config = ConfigDict(extra="allow")


class LocalPaths(_Section):
    """Windows PC側のパス。"""
    media_base: str = ""


class DeckPaths(_Section):
    """Steam Deck側のパス。"""
    rom_base: str = "/run/media/mmcblk0p1/Emulation/roms"
    gamelist_base: str = "/home/deck/.emulationstation/gamelists"
    media_base: str = "/home/deck/.emulationstation/downloaded_media"
    doujin_base: list[str] = Field(default_factory=list)
    steam_root: str = "/home/deck/.local/share/Steam"
    steam_user: str = ""
    """非Steamゲームを登録するSteamアカウント（userdata/ 配下のフォルダ名）。空なら1つしか無いときに自動で選ぶ。"""
    default_compat_tool: str = "proton_experimental"
    default_launch_options: str = "LANG=ja_JP.UTF-8 %command%"
    """Shift-JISの同人ゲームが文字化けしにくいよう、既定で日本語ロケールにする。"""

    def gamelist_path(self, system: str) -> str:
        return f"{self.gamelist_base.rstrip('/')}/{system}/gamelist.xml"

    def rom_dir(self, system: str) -> str:
        return f"{self.rom_base.rstrip('/')}/{system}"

    def media_dir(self, system: str) -> str:
        return f"{self.media_base.rstrip('/')}/{system}"


class SyncSettings(_Section):
    """Steam DeckへのSSH接続設定。"""
    host: str = ""
    port: int = 22
    username: str = "deck"
    password: str = ""


class Config(_Section):
    system: str = ""
    systems: list[str] = Field(default_factory=list)
    backup_max: int = 5
    windows: LocalPaths = Field(default_factory=LocalPaths)
    steam_deck: DeckPaths = Field(default_factory=DeckPaths)
    sync: SyncSettings = Field(default_factory=SyncSettings)

    def local_media_dir(self, system: str) -> Path:
        return Path(self.windows.media_base) / system


def load_config(path: Path | None = None) -> Config:
    p = path or config_path()
    if not p.exists():
        return Config()
    return Config.model_validate(json.loads(p.read_text(encoding="utf-8")))


def save_config(config: Config, path: Path | None = None) -> None:
    p = path or config_path()
    p.write_text(
        json.dumps(config.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
