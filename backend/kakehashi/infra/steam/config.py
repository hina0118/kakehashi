"""Steamの config.vdf（互換ツールの割り当て）と loginusers.vdf（アカウント一覧）の操作。"""
from __future__ import annotations

from pydantic import BaseModel

from kakehashi.infra.steam.text_vdf import KV

_COMPAT_PATH = ("InstallConfigStore", "Software", "Valve", "Steam", "CompatToolMapping")
_STEAMID64_BASE = 76561197960265728


def set_compat_tool(config: KV, appid: int, tool: str) -> None:
    """appID に互換ツール（Proton）を割り当てる。tool が空なら割り当てを外す。"""
    mapping = config.path(*_COMPAT_PATH, create=bool(tool))
    if mapping is None:
        return
    if not tool:
        mapping.remove(str(appid))
        return
    mapping.set(str(appid), KV([("name", tool), ("config", ""), ("priority", "250")]))


def get_compat_tool(config: KV, appid: int) -> str:
    mapping = config.path(*_COMPAT_PATH)
    entry = mapping.get(str(appid)) if mapping else None
    name = entry.get("name") if isinstance(entry, KV) else None
    return name if isinstance(name, str) else ""


class SteamUser(BaseModel):
    account_id: str
    """userdata/ 配下のフォルダ名（SteamID3 のアカウントID）"""
    account_name: str = ""
    persona_name: str = ""
    most_recent: bool = False


def parse_login_users(users: KV) -> list[SteamUser]:
    node = users.child("users")
    if node is None:
        return []
    result = []
    for steamid64, info in node.items:
        if not isinstance(info, KV) or not steamid64.isdigit():
            continue
        result.append(SteamUser(
            account_id=str(int(steamid64) - _STEAMID64_BASE),
            account_name=str(info.get("AccountName") or ""),
            persona_name=str(info.get("PersonaName") or ""),
            most_recent=(info.get("MostRecent") or info.get("mostrecent")) == "1",
        ))
    return result
