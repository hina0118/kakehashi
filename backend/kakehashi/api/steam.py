from __future__ import annotations

from fastapi import APIRouter, Response
from pydantic import BaseModel

from kakehashi.api.deps import Ctx
from kakehashi.errors import NotFoundError
from kakehashi.services.jobs import JobView
from kakehashi.services.steam import SteamStatus, art_png

router = APIRouter(tags=["steam"])


@router.get("/status")
def status(ctx: Ctx) -> SteamStatus:
    return ctx.steam.status()


@router.get("/compat-tools")
def compat_tools(ctx: Ctx) -> list[str]:
    return ctx.steam.compat_tools()


@router.get("/art/{game_id}/{kind}.png")
def art(ctx: Ctx, game_id: int, kind: str) -> Response:
    img = ctx.steam.art(game_id, kind)
    if img is None:
        raise NotFoundError(f"{kind} に使える画像がありません。")
    return Response(art_png(img), media_type="image/png", headers={"Cache-Control": "no-cache"})


class IdsRequest(BaseModel):
    ids: list[int]


@router.post("/apply")
def apply(ctx: Ctx, body: IdsRequest) -> JobView:
    return ctx.jobs.submit(
        "steam.apply", f"Steamに{len(body.ids)}件を登録",
        lambda job: [r.model_dump() for r in ctx.steam.apply(body.ids, job)],
    )


@router.post("/remove")
def remove(ctx: Ctx, body: IdsRequest) -> JobView:
    return ctx.jobs.submit(
        "steam.remove", f"Steamから{len(body.ids)}件を解除",
        lambda job: [r.model_dump() for r in ctx.steam.remove(body.ids, job)],
    )
