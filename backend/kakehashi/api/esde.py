from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

from kakehashi.api.deps import Ctx
from kakehashi.domain.esde import EsdeGame, GameUpdate, UpdateResult
from kakehashi.services.jobs import JobView

router = APIRouter(tags=["esde"])


@router.get("/systems")
def list_systems(ctx: Ctx) -> list[str]:
    return ctx.esde.list_systems()


@router.get("/{system}/games")
def list_games(
    ctx: Ctx, system: str, refresh: bool = False, include_unregistered: bool = False,
) -> list[EsdeGame]:
    games = list(ctx.esde.get_games(system, refresh=refresh))
    if include_unregistered:
        games += ctx.esde.find_unregistered_roms(system)
    return games


class UpdateRequest(BaseModel):
    updates: list[GameUpdate] = Field(default_factory=list)
    deleted: list[str] = Field(default_factory=list)


@router.post("/{system}/games/update")
def update_games(ctx: Ctx, system: str, body: UpdateRequest) -> UpdateResult:
    return ctx.esde.update_games(system, body.updates, body.deleted)


class UploadRomsRequest(BaseModel):
    files: list[str]
    overwrite: bool = False


@router.post("/{system}/roms/upload")
def upload_roms(ctx: Ctx, system: str, body: UploadRomsRequest) -> JobView:
    files = [Path(f) for f in body.files]
    return ctx.jobs.submit(
        "esde.upload_roms", f"{system}: ROMを{len(files)}件送信",
        lambda job: ctx.esde.upload_roms(system, files, job, overwrite=body.overwrite),
    )
