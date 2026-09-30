from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from kakehashi.api.deps import Ctx
from kakehashi.domain.doujin import DoujinGame, DoujinPatch
from kakehashi.infra.dlsite import DlsiteInfo
from kakehashi.services.doujin import DeckFolder, FolderCandidate
from kakehashi.services.jobs import JobView
from kakehashi.services.media import image_thumbnail

router = APIRouter(tags=["doujin"])


class PathRequest(BaseModel):
    path: str


class PathsRequest(BaseModel):
    paths: list[str]


@router.get("/games")
def list_games(ctx: Ctx) -> list[DoujinGame]:
    return ctx.doujin.list()


@router.post("/games")
def register(ctx: Ctx, body: PathRequest) -> DoujinGame:
    return ctx.doujin.register_folder(body.path)


@router.post("/games/register-many")
def register_many(ctx: Ctx, body: PathsRequest) -> list[DoujinGame]:
    return ctx.doujin.register_many(body.paths)


@router.post("/scan-folder")
def scan_folder(ctx: Ctx, body: PathRequest) -> list[FolderCandidate]:
    return ctx.doujin.scan_parent(body.path)


@router.get("/games/{game_id}")
def get_game(ctx: Ctx, game_id: int) -> DoujinGame:
    return ctx.doujin.get(game_id)


@router.patch("/games/{game_id}")
def update_game(ctx: Ctx, game_id: int, body: DoujinPatch) -> DoujinGame:
    return ctx.doujin.update(game_id, body)


@router.delete("/games/{game_id}")
def delete_game(ctx: Ctx, game_id: int) -> dict:
    ctx.doujin.delete(game_id)
    return {"deleted": game_id}


@router.get("/games/{game_id}/exe-candidates")
def exe_candidates(ctx: Ctx, game_id: int) -> list[str]:
    return ctx.doujin.exe_candidates(game_id)


# ---- 画像 ----

@router.get("/games/{game_id}/images/{kind}")
def image(ctx: Ctx, game_id: int, kind: str, w: int | None = None):
    p = ctx.doujin.image_path(game_id, kind)
    headers = {"Cache-Control": "no-cache"}
    if w:
        return Response(image_thumbnail(p, min(max(w, 16), 1024)), media_type="image/png", headers=headers)
    return FileResponse(p, headers=headers)


class ImageFileRequest(BaseModel):
    source: str


class ImageUrlRequest(BaseModel):
    url: str


@router.post("/games/{game_id}/images/{kind}/import-file")
def import_image_file(ctx: Ctx, game_id: int, kind: str, body: ImageFileRequest) -> DoujinGame:
    return ctx.doujin.import_image_file(game_id, kind, Path(body.source))


@router.post("/games/{game_id}/images/{kind}/import-url")
def import_image_url(ctx: Ctx, game_id: int, kind: str, body: ImageUrlRequest) -> DoujinGame:
    return ctx.doujin.import_image_url(game_id, kind, body.url)


@router.delete("/games/{game_id}/images/{kind}")
def delete_image(ctx: Ctx, game_id: int, kind: str) -> DoujinGame:
    return ctx.doujin.delete_image(game_id, kind)


# ---- DLsite ----

@router.get("/dlsite/{work_id}")
def dlsite(ctx: Ctx, work_id: str) -> DlsiteInfo:
    return ctx.doujin.fetch_dlsite(work_id)


# ---- Steam Deck ----

class TransferRequest(BaseModel):
    base: str | None = None
    overwrite: bool = False


@router.post("/games/{game_id}/transfer")
def transfer(ctx: Ctx, game_id: int, body: TransferRequest) -> JobView:
    title = ctx.doujin.get(game_id).title or f"id={game_id}"
    return ctx.jobs.submit(
        "doujin.transfer", f"{title} をDeckへ転送",
        lambda job: ctx.doujin.transfer(game_id, job, base=body.base, overwrite=body.overwrite),
    )


@router.post("/deck/scan")
def scan_deck(ctx: Ctx) -> list[DeckFolder]:
    return ctx.doujin.scan_deck()


@router.post("/deck/import")
def import_from_deck(ctx: Ctx, body: PathsRequest) -> list[DoujinGame]:
    return ctx.doujin.import_from_deck(body.paths)
