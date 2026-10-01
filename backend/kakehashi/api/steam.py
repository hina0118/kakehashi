from __future__ import annotations

from fastapi import APIRouter, Response
from pydantic import BaseModel

from kakehashi.api.deps import Ctx
from kakehashi.errors import NotFoundError
from kakehashi.services.jobs import JobView
from kakehashi.domain.doujin import DoujinGame
from kakehashi.services.steam import ArtDecision, GridImage, SteamScan, SteamStatus, art_png

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


class ApplyRequest(IdsRequest):
    overwrite_art: bool = False
    """Deckに既にあるライブラリ画像も台帳の画像で置き換えるか"""


@router.post("/apply")
def apply(ctx: Ctx, body: ApplyRequest) -> JobView:
    return ctx.jobs.submit(
        "steam.apply", f"Steamに{len(body.ids)}件を登録",
        lambda job: [r.model_dump() for r in ctx.steam.apply(body.ids, job, overwrite_art=body.overwrite_art)],
    )


@router.get("/art-status/{game_id}")
def art_status(ctx: Ctx, game_id: int) -> list[ArtDecision]:
    return ctx.steam.art_status(game_id)


@router.get("/grid/{game_id}")
def grid_images(ctx: Ctx, game_id: int) -> list[GridImage]:
    return ctx.steam.grid_images(game_id)


_MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".ico": "image/x-icon"}


@router.get("/grid/{game_id}/{kind}")
def grid_image(ctx: Ctx, game_id: int, kind: str) -> Response:
    data, ext = ctx.steam.grid_image_bytes(game_id, kind)
    return Response(data, media_type=_MEDIA_TYPES.get(ext, "application/octet-stream"))


class PullArtRequest(IdsRequest):
    kinds: list[str] | None = None
    overwrite: bool = False


@router.post("/pull-art")
def pull_art(ctx: Ctx, body: PullArtRequest) -> JobView:
    return ctx.jobs.submit(
        "steam.pull_art", f"Steamの画像を{len(body.ids)}件取り込み",
        lambda job: [r.model_dump() for r in ctx.steam.pull_art(body.ids, job, kinds=body.kinds, overwrite=body.overwrite)],
    )


@router.get("/shortcuts")
def shortcuts(ctx: Ctx) -> SteamScan:
    return ctx.steam.scan_shortcuts()


class ImportRequest(BaseModel):
    appids: list[int]


@router.post("/import")
def import_shortcuts(ctx: Ctx, body: ImportRequest) -> list[DoujinGame]:
    return ctx.steam.import_shortcuts(body.appids)


@router.post("/remove")
def remove(ctx: Ctx, body: IdsRequest) -> JobView:
    return ctx.jobs.submit(
        "steam.remove", f"Steamから{len(body.ids)}件を解除",
        lambda job: [r.model_dump() for r in ctx.steam.remove(body.ids, job)],
    )
