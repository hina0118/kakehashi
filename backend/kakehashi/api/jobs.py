from fastapi import APIRouter

from kakehashi.api.deps import Ctx
from kakehashi.errors import NotFoundError
from kakehashi.services.jobs import JobView

router = APIRouter(tags=["jobs"])


@router.get("")
def list_jobs(ctx: Ctx) -> list[JobView]:
    return ctx.jobs.list()


@router.get("/{job_id}")
def get_job(ctx: Ctx, job_id: str) -> JobView:
    job = ctx.jobs.get(job_id)
    if job is None:
        raise NotFoundError(f"ジョブが見つかりません: {job_id}")
    return job
