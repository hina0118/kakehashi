"""時間のかかる処理（転送・ダウンロード・AI処理）をバックグラウンドで実行し、進捗を公開する。"""
from __future__ import annotations

import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

JobStatus = Literal["running", "done", "error"]


class JobView(BaseModel):
    id: str
    kind: str
    title: str
    status: JobStatus
    done: int = 0
    total: int = 0
    messages: list[str] = Field(default_factory=list)
    error: str | None = None
    result: Any = None
    started_at: datetime
    finished_at: datetime | None = None


class Job:
    """ジョブ関数に渡される進捗報告用オブジェクト。"""

    _MAX_MESSAGES = 200

    def __init__(self, kind: str, title: str) -> None:
        self._lock = threading.Lock()
        self._view = JobView(
            id=uuid.uuid4().hex[:12], kind=kind, title=title, status="running", started_at=datetime.now(),
        )

    @property
    def id(self) -> str:
        return self._view.id

    def progress(self, done: int, total: int) -> None:
        with self._lock:
            self._view.done, self._view.total = done, total

    def log(self, message: str) -> None:
        with self._lock:
            msgs = self._view.messages
            msgs.append(message)
            del msgs[:-self._MAX_MESSAGES]

    def _finish(self, status: JobStatus, result: Any = None, error: str | None = None) -> None:
        with self._lock:
            self._view.status, self._view.result, self._view.error = status, result, error
            self._view.finished_at = datetime.now()

    def view(self) -> JobView:
        with self._lock:
            return self._view.model_copy(deep=True)


class JobManager:
    _KEEP = 50

    def __init__(self, workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="kakehashi-job")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(self, kind: str, title: str, fn: Callable[[Job], Any]) -> JobView:
        job = Job(kind, title)
        with self._lock:
            self._jobs[job.id] = job
            for old in list(self._jobs)[:-self._KEEP]:
                if self._jobs[old].view().status != "running":
                    del self._jobs[old]

        def _run() -> None:
            try:
                job._finish("done", result=fn(job))
            except Exception as e:
                job.log(traceback.format_exc(limit=3))
                job._finish("error", error=str(e) or type(e).__name__)

        self._executor.submit(_run)
        return job.view()

    def get(self, job_id: str) -> JobView | None:
        with self._lock:
            job = self._jobs.get(job_id)
        return job.view() if job else None

    def list(self) -> list[JobView]:
        with self._lock:
            jobs = list(self._jobs.values())
        return [j.view() for j in reversed(jobs)]
