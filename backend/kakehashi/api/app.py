from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from kakehashi.api import esde, settings
from kakehashi.config import PROJECT_ROOT
from kakehashi.context import AppContext
from kakehashi.infra.deck import DeckConnectionError, DeckNotConfiguredError

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


def create_app(ctx: AppContext | None = None) -> FastAPI:
    app = FastAPI(title="kakehashi")
    app.state.ctx = ctx or AppContext()

    app.include_router(settings.router, prefix="/api/settings")
    app.include_router(esde.router, prefix="/api/esde")

    @app.exception_handler(DeckNotConfiguredError)
    async def _not_configured(_req: Request, exc: DeckNotConfiguredError):
        return JSONResponse(status_code=400, content={"detail": str(exc), "code": "deck_not_configured"})

    @app.exception_handler(ValueError)
    async def _invalid(_req: Request, exc: ValueError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(DeckConnectionError)
    async def _deck_unreachable(_req: Request, exc: DeckConnectionError):
        return JSONResponse(status_code=502, content={"detail": str(exc), "code": "deck_unreachable"})

    if FRONTEND_DIST.is_dir():
        _mount_frontend(app, FRONTEND_DIST)
    return app


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    async def _spa(path: str):
        # public/ 由来のファイル（favicon等）はそのまま返し、それ以外はindex.htmlを返す
        if path.startswith("api/"):
            raise HTTPException(status_code=404)
        file = (root / path).resolve()
        if path and file.is_file() and file.is_relative_to(root):
            return FileResponse(file)
        return FileResponse(root / "index.html")
