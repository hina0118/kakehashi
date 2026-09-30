from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from kakehashi.api import esde, jobs, local, media, settings
from kakehashi.config import PROJECT_ROOT
from kakehashi.context import AppContext
from kakehashi.errors import NotFoundError
from kakehashi.infra.deck import DeckConnectionError, DeckNotConfiguredError

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"

# 更新系リクエストに必須のヘッダ。独自ヘッダはCORSのプリフライト対象になるため、
# 他サイトのページからローカルのkakehashiを操作される（CSRF）のを防げる。
CSRF_HEADER = "X-Kakehashi"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


def create_app(ctx: AppContext | None = None) -> FastAPI:
    app = FastAPI(title="kakehashi")
    app.state.ctx = ctx or AppContext()

    @app.middleware("http")
    async def _guard(request: Request, call_next):
        # DNSリバインディング対策: ローカル以外のHost名で来たリクエストは拒否する
        host = request.headers.get("host", "").rsplit(":", 1)[0]
        if host not in _LOCAL_HOSTS:
            return JSONResponse(status_code=403, content={"detail": "localhost 以外からのアクセスは許可していません。"})
        if request.url.path.startswith("/api/") and request.method not in _SAFE_METHODS \
                and request.headers.get(CSRF_HEADER) != "1":
            return JSONResponse(status_code=403, content={"detail": f"{CSRF_HEADER} ヘッダがありません。"})
        return await call_next(request)

    app.include_router(settings.router, prefix="/api/settings")
    app.include_router(esde.router, prefix="/api/esde")
    app.include_router(media.router, prefix="/api/esde")
    app.include_router(media.global_router, prefix="/api/media")
    app.include_router(jobs.router, prefix="/api/jobs")
    app.include_router(local.router, prefix="/api/local")

    @app.exception_handler(DeckNotConfiguredError)
    async def _not_configured(_req: Request, exc: DeckNotConfiguredError):
        return JSONResponse(status_code=400, content={"detail": str(exc), "code": "deck_not_configured"})

    @app.exception_handler(DeckConnectionError)
    async def _deck_unreachable(_req: Request, exc: DeckConnectionError):
        return JSONResponse(status_code=502, content={"detail": str(exc), "code": "deck_unreachable"})

    @app.exception_handler(NotFoundError)
    async def _not_found(_req: Request, exc: NotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def _invalid(_req: Request, exc: ValueError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    if FRONTEND_DIST.is_dir():
        _mount_frontend(app, FRONTEND_DIST)
    return app


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    async def _spa(path: str):
        # ビルド済みファイル（assets/・favicon等）はそのまま返し、それ以外はindex.htmlを返す
        if path.startswith("api/"):
            raise HTTPException(status_code=404)
        file = (root / path).resolve()
        if path and file.is_file() and file.is_relative_to(root):
            return FileResponse(file)
        return FileResponse(root / "index.html")
