from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import DbDep
from shared.constants import CrawlStatus
from shared.models.crawl import CrawlJob

router = APIRouter()


def _job_dict(j: CrawlJob) -> dict:
    return {
        c.name: str(getattr(j, c.name)) if getattr(j, c.name) is not None else None
        for c in j.__table__.columns
    }


@router.get("")
async def list_crawls(
    limit: int = Query(50, le=200),
    status: str | None = None,
    session: AsyncSession = DbDep,
):
    q = select(CrawlJob).order_by(CrawlJob.created_at.desc()).limit(limit)
    if status:
        q = q.where(CrawlJob.status == status)
    result = await session.execute(q)
    jobs = result.scalars().all()
    return {"jobs": [_job_dict(j) for j in jobs], "total": len(jobs)}


@router.get("/{job_id}")
async def get_crawl(job_id: str, session: AsyncSession = DbDep):
    import uuid

    try:
        uid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(400, "Invalid job_id — must be a UUID")

    job = await session.get(CrawlJob, uid)
    if not job:
        raise HTTPException(404, "Crawl job not found")
    return _job_dict(job)


@router.post("/retry")
async def retry_crawl(job_id: str, session: AsyncSession = DbDep):
    import uuid

    from modules.dispatcher.dispatcher import dispatch_job

    try:
        uid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(400, "Invalid job_id — must be a UUID")

    job = await session.get(CrawlJob, uid)
    if not job:
        raise HTTPException(404, "Crawl job not found")

    if job.status not in (
        CrawlStatus.FAILED.value,
        CrawlStatus.BLOCKED.value,
        CrawlStatus.RATE_LIMITED.value,
    ):
        raise HTTPException(409, f"Job status '{job.status}' is not retryable")

    # Reset status to pending
    await session.execute(
        update(CrawlJob)
        .where(CrawlJob.id == uid)
        .values(status=CrawlStatus.PENDING.value, error_message=None)
    )
    await session.commit()

    # Re-enqueue
    platform = job.meta.get("platform") or job.job_type
    identifier = job.seed_identifier or ""
    person_id = str(job.person_id) if job.person_id else None

    await dispatch_job(
        platform=platform,
        identifier=identifier,
        person_id=person_id,
        priority="high",
        job_id=str(job.id),
    )

    return {"message": "Job re-queued", "job_id": job_id, "status": CrawlStatus.PENDING.value}
