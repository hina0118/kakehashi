from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from kakehashi.domain.media import IMAGE_SUFFIXES, VIDEO_SUFFIXES
from kakehashi.infra import local_dialog

router = APIRouter(tags=["local"])

_FILETYPES = {
    "image": [("画像", " ".join(f"*{s}" for s in sorted(IMAGE_SUFFIXES)))],
    "video": [("動画", " ".join(f"*{s}" for s in sorted(VIDEO_SUFFIXES)))],
    "pdf": [("PDF", "*.pdf")],
    "media": [
        ("画像・動画・PDF", " ".join(f"*{s}" for s in sorted(IMAGE_SUFFIXES | VIDEO_SUFFIXES | {".pdf"}))),
    ],
}


class PickRequest(BaseModel):
    mode: local_dialog.DialogMode = "file"
    title: str = "ファイルを選択"
    filetypes: str | None = None
    """"image" / "video" / "pdf" / "media" のいずれか。省略時はすべてのファイル。"""


@router.post("/pick")
async def pick(body: PickRequest) -> list[str]:
    """このPCでファイル選択ダイアログを開き、選ばれたパスを返す（キャンセル時は空）。"""
    return await run_in_threadpool(
        local_dialog.pick, body.mode, body.title, _FILETYPES.get(body.filetypes or ""),
    )
