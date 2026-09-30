from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from kakehashi.api.deps import Ctx
from kakehashi.domain.media import GameMedia, MediaFile
from kakehashi.services.jobs import Job, JobView
from kakehashi.services.media import Capabilities, image_thumbnail
from kakehashi.services.previews import PreviewInfo

router = APIRouter(tags=["media"])
# 機種によらないエンドポイント（/api/media 配下）
global_router = APIRouter(tags=["media"])


@global_router.get("/capabilities")
def capabilities(ctx: Ctx) -> Capabilities:
    return ctx.media.capabilities


@router.get("/{system}/media")
def game_media(ctx: Ctx, system: str, path: str) -> GameMedia:
    return ctx.media.game_media(system, path)


@router.get("/{system}/media/coverage")
def coverage(ctx: Ctx, system: str) -> dict[str, dict[str, str]]:
    return ctx.media.coverage(system)


@router.get("/{system}/media/pending-deletions")
def pending_deletions(ctx: Ctx, system: str) -> list[str]:
    return ctx.media.pending_deletions(system)


@router.get("/{system}/media/file/{folder}/{filename}")
def media_file(ctx: Ctx, system: str, folder: str, filename: str, w: int | None = None):
    p = ctx.media.file_path(system, folder, filename)
    headers = {"Cache-Control": "no-cache"}
    if w:
        return Response(image_thumbnail(p, min(max(w, 16), 1024)), media_type="image/png", headers=headers)
    return FileResponse(p, headers=headers)


class ImportFileRequest(BaseModel):
    path: str
    source: str


class ImportUrlRequest(BaseModel):
    path: str
    url: str


class GameFolderRequest(BaseModel):
    path: str


@router.post("/{system}/media/{folder}/import-file")
def import_file(ctx: Ctx, system: str, folder: str, body: ImportFileRequest) -> MediaFile:
    return ctx.media.import_file(system, body.path, folder, Path(body.source))


@router.post("/{system}/media/{folder}/import-url")
def import_url(ctx: Ctx, system: str, folder: str, body: ImportUrlRequest) -> JobView:
    return ctx.jobs.submit(
        "media.import_url", f"{folder} をURLから取得",
        lambda job: ctx.media.import_url(system, body.path, folder, body.url).model_dump(),
    )


@router.post("/{system}/media/{folder}/delete")
def delete_media(ctx: Ctx, system: str, folder: str, body: GameFolderRequest) -> dict:
    return {"deleted": ctx.media.delete(system, body.path, folder)}


# ---- 生成 ----

class Box3dRequest(BaseModel):
    path: str
    spine_ratio: float = Field(0.08, ge=0.02, le=0.25)
    angle_pct: float = Field(0.30, ge=0.05, le=0.60)
    shadow: bool = True
    spine_text: str = ""


class CropRequest(BaseModel):
    path: str
    folder: str = "covers"
    box: tuple[int, int, int, int]


@router.post("/{system}/media/preview/3dbox")
def preview_3dbox(ctx: Ctx, system: str, body: Box3dRequest) -> PreviewInfo:
    return ctx.media.preview_3dbox(
        system, body.path, spine_ratio=body.spine_ratio, angle_pct=body.angle_pct,
        shadow=body.shadow, spine_text=body.spine_text,
    )


@router.post("/{system}/media/preview/miximage")
def preview_miximage(ctx: Ctx, system: str, body: GameFolderRequest) -> PreviewInfo:
    return ctx.media.preview_miximage(system, body.path)


@router.post("/{system}/media/preview/crop")
def preview_crop(ctx: Ctx, system: str, body: CropRequest) -> PreviewInfo:
    return ctx.media.preview_crop(system, body.path, body.folder, body.box)


@router.post("/{system}/media/preview/ai-logo")
def preview_ai_logo(ctx: Ctx, system: str, body: GameFolderRequest) -> JobView:
    def run(job: Job) -> dict:
        job.log("初回はモデルの読み込みに時間がかかります…")
        return ctx.media.preview_ai_logo(system, body.path).model_dump()

    return ctx.jobs.submit("media.ai_logo", "AIでロゴを抽出", run)


@global_router.get("/previews/{preview_id}.png")
def preview_image(ctx: Ctx, preview_id: str) -> Response:
    return Response(ctx.media.preview_bytes(preview_id), media_type="image/png")


class SavePreviewRequest(BaseModel):
    path: str
    preview_id: str


@router.post("/{system}/media/{folder}/save-preview")
def save_preview(ctx: Ctx, system: str, folder: str, body: SavePreviewRequest) -> MediaFile:
    return ctx.media.save_preview(system, body.path, folder, body.preview_id)


# ---- Deckとの同期 ----

class SyncRequest(BaseModel):
    direction: Literal["pull", "push"]
    overwrite: bool = False
    folders: list[str] | None = None


@router.post("/{system}/media/sync")
def sync(ctx: Ctx, system: str, body: SyncRequest) -> JobView:
    if body.direction == "pull":
        return ctx.jobs.submit(
            "media.pull", f"{system}: Deckからメディアを取得",
            lambda job: ctx.media.pull(system, job, overwrite=body.overwrite).model_dump(),
        )
    return ctx.jobs.submit(
        "media.push", f"{system}: メディアをDeckへ送信",
        lambda job: ctx.media.push(system, job, folders=body.folders, overwrite=body.overwrite).model_dump(),
    )
