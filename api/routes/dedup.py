"""Deduplication API routes — find and merge duplicate person records."""

import logging
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select as sa_select
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import DbDep
from api.serializers import _serialize
from modules.enrichers.auto_dedup import AutoDedupDaemon
from modules.enrichers.deduplication import AsyncMergeExecutor, score_person_dedup
from shared.models.dedup_review import DedupReview

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Auto-dedup helper — isolated for easier mocking ──────────────────────────


async def get_auto_queue_rows(session: AsyncSession) -> list[dict]:
    """Fetch pending (unreviewed) DedupReview rows."""
    result = await session.execute(
        sa_select(DedupReview)
        .where(DedupReview.reviewed == False)  # noqa: E712
        .order_by(DedupReview.similarity_score.desc())
        .limit(200)
    )
    rows = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "person_a_id": str(r.person_a_id),
            "person_b_id": str(r.person_b_id),
            "similarity_score": r.similarity_score,
            "reviewed": r.reviewed,
            "decision": r.decision,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


# ── Request schemas ────────────────────────────────────────────────────────────


class MergeRequest(BaseModel):
    canonical_id: str
    duplicate_id: str


class BatchCandidatesRequest(BaseModel):
    person_ids: list[str]  # length enforced explicitly in the handler (max 100)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _validate_uuid(value: str) -> uuid.UUID:
    """Parse and return a UUID, raising HTTP 400 on failure."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        raise HTTPException(400, f"Invalid UUID: {value!r}")


def _candidate_to_dict(c) -> dict:
    return {
        "id_a": c.id_a,
        "id_b": c.id_b,
        "similarity_score": c.similarity_score,
        "match_reasons": c.match_reasons,
    }


# ── Endpoints — fixed paths MUST be declared before parameterised paths ────────


@router.get("/auto-queue")
async def dedup_auto_queue(session: AsyncSession = DbDep):
    """Return all pending DedupReview rows ordered by score descending."""
    rows = await get_auto_queue_rows(session)
    return {"reviews": rows, "count": len(rows)}


@router.post("/auto-merge/run")
async def dedup_auto_merge_run(session: AsyncSession = DbDep):
    """Trigger one immediate dedup batch outside the regular schedule."""
    daemon = AutoDedupDaemon()
    try:
        await daemon._run_batch(session)
    except Exception as exc:
        logger.exception("Manual dedup batch failed")
        raise HTTPException(500, "Dedup batch failed") from exc
    return {"status": "ok", "message": "Dedup batch completed"}


@router.post("/merge")
async def merge_persons(req: MergeRequest, session: AsyncSession = DbDep):
    """Merge duplicate_id into canonical_id."""
    _validate_uuid(req.canonical_id)
    _validate_uuid(req.duplicate_id)

    plan = {
        "canonical_id": req.canonical_id,
        "duplicate_id": req.duplicate_id,
    }

    try:
        result = await AsyncMergeExecutor().execute(plan, session)
    except Exception as exc:
        logger.exception(
            "AsyncMergeExecutor failed canonical=%s dup=%s",
            req.canonical_id,
            req.duplicate_id,
        )
        raise HTTPException(500, "Internal error") from exc

    if not result.get("merged"):
        raise HTTPException(400, result.get("error", "Merge failed"))

    return _serialize(result)


@router.post("/batch-candidates")
async def batch_candidates(req: BatchCandidatesRequest, session: AsyncSession = DbDep):
    """Find merge candidates for a list of person IDs (max 100)."""
    if len(req.person_ids) > 100:
        raise HTTPException(400, "Maximum 100 person_ids per request")

    # Validate all IDs before doing any work
    for pid in req.person_ids:
        _validate_uuid(pid)

    seen_pairs: set[frozenset] = set()
    all_candidates: list[dict] = []

    # Sequential — never asyncio.gather on the same session
    for pid in req.person_ids:
        try:
            candidates = await score_person_dedup(pid, session)
        except Exception:
            logger.exception("score_person_dedup failed person_id=%s (batch)", pid)
            continue

        for c in candidates:
            pair = frozenset({c.id_a, c.id_b})
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            all_candidates.append(_candidate_to_dict(c))

    return {
        "candidates": all_candidates,
        "count": len(all_candidates),
        "persons_scanned": len(req.person_ids),
    }


@router.post("/{person_id}/candidates")
async def get_candidates(person_id: str, session: AsyncSession = DbDep):
    """Find merge candidates for a single person."""
    _validate_uuid(person_id)
    try:
        candidates = await score_person_dedup(person_id, session)
    except Exception as exc:
        logger.exception("score_person_dedup failed person_id=%s", person_id)
        raise HTTPException(500, "Internal error") from exc

    return {
        "person_id": person_id,
        "candidates": [_candidate_to_dict(c) for c in candidates],
        "count": len(candidates),
    }


@router.get("/{person_id}/merge-history")
async def merge_history(person_id: str, session: AsyncSession = DbDep):
    """Return audit log merge events for a person (last 50)."""
    _validate_uuid(person_id)

    try:
        result = await session.execute(
            sa_text(
                "SELECT * FROM audit_log WHERE person_id = :id ORDER BY access_time DESC LIMIT 50"
            ),
            {"id": person_id},
        )
        rows = result.mappings().all()
    except Exception as exc:
        logger.exception("merge-history query failed person_id=%s", person_id)
        raise HTTPException(500, "Internal error") from exc

    history = [_serialize(dict(row)) for row in rows]

    return {
        "person_id": person_id,
        "history": history,
    }
