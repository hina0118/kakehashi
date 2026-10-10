from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from kakehashi.api.deps import Ctx
from kakehashi.domain.doujin import DoujinGame, DoujinPatch
from kakehashi.domain.works import WorkInfo
from kakehashi.services.doujin import DeckFolder, DuplicateHit, FolderCandidate, SearchResult
from kakehashi.services.doujin_sync import DeckCheck, SyncStatus, TextContent, TextFile, UpdatePlan
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


@router.post("/duplicates")
def find_duplicates(ctx: Ctx, body: PathRequest) -> list[DuplicateHit]:
    return ctx.doujin.find_duplicates(body.path)


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


# ---- 販売サイト ----

@router.get("/works/{store}/{work_id}")
def fetch_work(ctx: Ctx, store: str, work_id: str) -> WorkInfo:
    return ctx.doujin.fetch_work(store, work_id)


@router.get("/works/search")
def search_works(ctx: Ctx, q: str, stores: str = "") -> SearchResult:
    return ctx.doujin.search_works(q, [s for s in stores.split(",") if s] or None)


# ---- Steam Deck ----

class PushRequest(BaseModel):
    base: str | None = None
    force: bool = False
    """PCとDeckの両方で変わったファイルもPCの内容で上書きする"""


@router.post("/games/{game_id}/push")
def push(ctx: Ctx, game_id: int, body: PushRequest) -> JobView:
    title = ctx.doujin.get(game_id).title or f"id={game_id}"
    return ctx.jobs.submit(
        "doujin.push", f"{title} をDeckへ反映",
        lambda job: ctx.doujin_sync.push(game_id, job, base=body.base, force=body.force).model_dump(),
    )


class PullRequest(BaseModel):
    force: bool = False
    """PCで変更してまだ反映していないファイルもDeckの内容で上書きする"""


@router.post("/games/{game_id}/pull")
def pull(ctx: Ctx, game_id: int, body: PullRequest) -> JobView:
    title = ctx.doujin.get(game_id).title or f"id={game_id}"
    return ctx.jobs.submit(
        "doujin.pull", f"{title} をDeckから取得",
        lambda job: ctx.doujin_sync.pull(game_id, job, force=body.force).model_dump(),
    )


class MoveRequest(BaseModel):
    base: str
    """移動先の格納先"""


@router.post("/games/{game_id}/move")
def move(ctx: Ctx, game_id: int, body: MoveRequest) -> JobView:
    game = ctx.doujin.get(game_id)

    def run(job):
        result = ctx.doujin_sync.move(game_id, body.base, job).model_dump()
        result["steam"] = None
        if game.steam_registered_at:
            job.log("Steamの登録を移動先に合わせます")
            [r] = ctx.steam.apply([game_id], job)
            result["steam"] = r.model_dump()
        return result

    return ctx.jobs.submit("doujin.move", f"{game.title or f'id={game_id}'} を {body.base} へ移動", run)


@router.get("/games/{game_id}/sync-status")
def sync_status(ctx: Ctx, game_id: int) -> SyncStatus:
    return ctx.doujin_sync.status(game_id)


class UpdateSourceRequest(BaseModel):
    source: str
    root: str | None = None
    """作品フォルダに当たる位置。省略すると自動で選ぶ"""


@router.post("/games/{game_id}/update/plan")
def plan_update(ctx: Ctx, game_id: int, body: UpdateSourceRequest) -> UpdatePlan:
    return ctx.doujin_sync.plan_update(game_id, body.source, body.root)


class ApplyUpdateRequest(BaseModel):
    source: str
    root: str
    version: str = ""


@router.post("/games/{game_id}/update/apply")
def apply_update(ctx: Ctx, game_id: int, body: ApplyUpdateRequest) -> JobView:
    title = ctx.doujin.get(game_id).title or f"id={game_id}"
    return ctx.jobs.submit(
        "doujin.update", f"{title} に更新データを適用",
        lambda job: ctx.doujin_sync.apply_update(game_id, body.source, body.root, body.version, job).model_dump(),
    )


@router.get("/games/{game_id}/deck-texts")
def deck_texts(ctx: Ctx, game_id: int) -> list[TextFile]:
    return ctx.doujin_sync.deck_texts(game_id)


@router.get("/games/{game_id}/deck-text")
def read_deck_text(ctx: Ctx, game_id: int, path: str) -> TextContent:
    return ctx.doujin_sync.read_deck_text(game_id, path)


class IdsRequest(BaseModel):
    ids: list[int]


@router.post("/deck/check")
def check_deck(ctx: Ctx) -> DeckCheck:
    return ctx.doujin_sync.check_deck()


@router.post("/deck/unlink")
def unlink_deck(ctx: Ctx, body: IdsRequest) -> dict:
    return {"unlinked": ctx.doujin_sync.unlink_deck(body.ids)}


@router.post("/deck/scan")
def scan_deck(ctx: Ctx) -> list[DeckFolder]:
    return ctx.doujin.scan_deck()


@router.post("/deck/import")
def import_from_deck(ctx: Ctx, body: PathsRequest) -> list[DoujinGame]:
    return ctx.doujin.import_from_deck(body.paths)
