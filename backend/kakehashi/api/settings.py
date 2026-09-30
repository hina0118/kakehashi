from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from kakehashi.api.deps import Ctx
from kakehashi.config import DeckPaths, LocalPaths

router = APIRouter(tags=["settings"])


class SyncView(BaseModel):
    host: str
    port: int
    username: str
    password_set: bool


class SyncInput(BaseModel):
    host: str
    port: int = 22
    username: str = "deck"
    password: str | None = None
    """None のときは保存済みのパスワードを維持する。"""


class SettingsView(BaseModel):
    systems: list[str]
    backup_max: int
    windows: LocalPaths
    steam_deck: DeckPaths
    sync: SyncView


class SettingsInput(BaseModel):
    systems: list[str]
    backup_max: int
    windows: LocalPaths
    steam_deck: DeckPaths
    sync: SyncInput


def _view(ctx: Ctx) -> SettingsView:
    c = ctx.config
    return SettingsView(
        systems=c.systems, backup_max=c.backup_max, windows=c.windows, steam_deck=c.steam_deck,
        sync=SyncView(
            host=c.sync.host, port=c.sync.port, username=c.sync.username,
            password_set=bool(c.sync.password),
        ),
    )


@router.get("")
def get_settings(ctx: Ctx) -> SettingsView:
    return _view(ctx)


@router.put("")
def put_settings(ctx: Ctx, body: SettingsInput) -> SettingsView:
    sync = ctx.config.sync.model_copy(update=body.sync.model_dump(exclude_none=True))
    ctx.update_config(ctx.config.model_copy(update={
        "systems": body.systems, "backup_max": body.backup_max,
        "windows": body.windows, "steam_deck": body.steam_deck, "sync": sync,
    }))
    return _view(ctx)


class ConnectionResult(BaseModel):
    ok: bool
    message: str


@router.post("/test-connection")
def test_connection(ctx: Ctx) -> ConnectionResult:
    with ctx.connect() as fs:
        found = fs.exists(ctx.config.steam_deck.gamelist_base)
    if found:
        return ConnectionResult(ok=True, message="接続しました。")
    return ConnectionResult(
        ok=True, message=f"接続しましたが、gamelist_base（{ctx.config.steam_deck.gamelist_base}）が見つかりません。",
    )
