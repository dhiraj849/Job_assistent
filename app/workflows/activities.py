"""Temporal activities: thin wrappers around existing services.

All I/O (browser, database, Qdrant, LLM) lives here, because workflow code
must stay deterministic. Arguments and results are our Pydantic models;
the worker and clients use the Pydantic data converter (app/workflows/client.py).
"""

import asyncio
import random
from datetime import datetime
from functools import cache

import structlog
from qdrant_client import QdrantClient
from temporalio import activity
from temporalio.exceptions import ApplicationError

from app.config import settings
from app.db.database import SessionLocal
from app.browser.job_applier import NaukriJobApplier
from app.db.job_repository import JobRepository
from app.job_sources.naukri import NaukriJobSource
from app.job_sources.naukri_detail import fetch_job_page
from app.job_sources.naukri_detail_parser import DetailParseError, parse_job_detail
from app.models.apply_result import ApplyResult
from app.models.candidate_profile import CandidateProfile
from app.models.decision import Decision
from app.models.job import Job
from app.models.job_match_item import JobMatchItem
from app.models.job_status import JobStatus
from app.services.apply_service import ApplyService
from app.services.job_filter_service import JobFilterService
from app.services.job_match_level_service import JobMatchLevelService
from app.services.job_match_service import JobMatchService
from app.services.job_ranker import JobRanker
from app.services.job_score_service import JobScoreService
from app.services.profile_loader import load_profile
from app.vector.embedder import Embedder
from app.vector.job_vector_store import JobVectorStore

logger = structlog.get_logger(__name__)


def _load_profile() -> CandidateProfile:
    # Read on every call, so profile edits apply without restarting the worker.
    return load_profile(settings.PROFILE_PATH)


@cache
def _ranker() -> JobRanker:
    # Loading the embedding model is slow; build it once per worker process.
    return JobRanker(
        embedder=Embedder(),
        store=JobVectorStore(QdrantClient(url=settings.QDRANT_URL)),
    )


# ---------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------


@activity.defn
async def discover_jobs(keyword: str, location: str) -> list[Job]:
    """Scrape Naukri for jobs matching keyword + location."""
    source = NaukriJobSource(
        keyword=keyword,
        location=location,
        headless=settings.BROWSER_HEADLESS,
        timeout_ms=settings.BROWSER_TIMEOUT_MS,
    )
    jobs = await source.get_jobs()

    logger.info(
        "activity_discover_jobs_done",
        count=len(jobs),
        attempt=activity.info().attempt,
    )
    return jobs


@activity.defn
async def save_jobs(jobs: list[Job]) -> list[int]:
    """Save jobs to Postgres. Returns the ids of the NEW jobs."""
    # Own session per activity: each attempt gets a fresh transaction,
    # so a retry never reuses a broken session.
    async with SessionLocal() as session:
        repository = JobRepository(session)
        new_jobs = await repository.save_jobs(jobs, source="naukri")
        ids_by_url = await repository.get_ids_by_urls([job.url for job in new_jobs])

    return list(ids_by_url.values())


# ---------------------------------------------------------------
# Per-job application
# ---------------------------------------------------------------


async def _get_job(job_id: int) -> Job:
    async with SessionLocal() as session:
        job = await JobRepository(session).get_job(job_id)

    if job is None:
        raise ValueError(f"Job {job_id} not found")
    return job


@activity.defn
async def load_job(job_id: int) -> Job:
    return await _get_job(job_id)


@activity.defn
async def fetch_job_details(job_id: int) -> Job:
    """Read the job's detail page (full JD + details), save it, return the job.

    Runs on BROWSER_TASK_QUEUE (one at a time). Already fetched -> no
    request at all, so a retry or a re-run workflow costs Naukri nothing.
    A page that loads but cannot be parsed is non-retryable: reading the
    same markup again gives the same result.
    """
    job = await _get_job(job_id)
    if job.details is not None:
        return job

    # Polite gap before every request; with one activity at a time on the
    # browser queue this is the minimum time between two Naukri pages.
    # Random is fine here: activities may be non-deterministic, workflows not.
    await asyncio.sleep(
        settings.DETAIL_PAGE_DELAY_SECONDS + random.uniform(0, settings.DETAIL_PAGE_JITTER_SECONDS)
    )
    html = await fetch_job_page(
        job.url, headless=settings.BROWSER_HEADLESS, timeout_ms=settings.BROWSER_TIMEOUT_MS
    )

    try:
        page = parse_job_detail(html)
    except DetailParseError as error:
        logger.error("job_detail_parse_failed", job_id=job_id, url=job.url, error=str(error))
        raise ApplicationError(str(error), type="DetailParseError", non_retryable=True) from error

    async with SessionLocal() as session:
        await JobRepository(session).save_details(job_id, page)
    return await _get_job(job_id)


@activity.defn
async def filter_job(job: Job) -> bool:
    """True if the keyword filter keeps this job."""
    return bool(JobFilterService().filter_jobs([job]))


@activity.defn
async def semantic_score(job_id: int, job: Job) -> float | None:
    """Cosine similarity to the profile, or None if below MIN_SCORE."""
    # Embedding + the sync Qdrant client block; run them in a thread so the
    # worker's event loop keeps serving other activities.
    ranked = await asyncio.to_thread(
        _ranker().rank, _load_profile(), [(job_id, job)], 1
    )
    return ranked[0][1] if ranked else None


@activity.defn
async def match_job(job: Job) -> JobMatchItem:
    """LLM evaluation + deterministic score and level."""
    result = await JobMatchService().match(_load_profile(), job)

    overall_score = JobScoreService().calculate(
        skill_match=result.skill_match,
        role_match=result.role_match,
        experience_match=result.experience_match,
    )

    return JobMatchItem(
        job=job,
        match=result,
        overall_score=overall_score,
        match_level=JobMatchLevelService().classify(overall_score),
    )


@activity.defn
async def save_match(job_id: int, item: JobMatchItem) -> None:
    async with SessionLocal() as session:
        await JobRepository(session).save_match(
            job_id, item.match, item.overall_score, item.match_level
        )


@activity.defn
async def update_job_status(job_id: int, status: JobStatus) -> None:
    # A refused write (job already applied live) is logged by the repository,
    # not raised: retrying would never succeed, and the job's real state is fine.
    async with SessionLocal() as session:
        await JobRepository(session).update_status(job_id, status)


@activity.defn
async def is_applied_live(job_id: int) -> bool:
    """True if applications says this job was really applied (not a dry run)."""
    async with SessionLocal() as session:
        return await JobRepository(session).is_applied_live(job_id)


@activity.defn
async def record_approval(job_id: int, approved_at: datetime, note: str) -> None:
    """Store my approval: applications row (pending) + job_decisions row +
    jobs.status=approved, one commit.

    Idempotent: a retry rewrites the same applications values, and the
    decision row is keyed by the workflow run id. A job already applied live
    is left alone; apply_job then returns ALREADY_APPLIED.
    """
    # Read here, not passed by the workflow: the args stay the same, so
    # histories from before job_decisions existed still replay.
    run_id = activity.info().workflow_run_id
    async with SessionLocal() as session:
        await JobRepository(session).record_approval(job_id, approved_at, note, run_id)


@activity.defn
async def record_decision(job_id: int, decision: Decision, decided_at: datetime, note: str) -> None:
    """Log a rejection or expiry (job_decisions) + set jobs.status, one commit."""
    run_id = activity.info().workflow_run_id
    async with SessionLocal() as session:
        await JobRepository(session).record_decision(job_id, decision, decided_at, note, run_id)


@activity.defn
async def expire_approval(job_id: int, reason: str) -> None:
    """Approved but never tried (daily cap stayed full): applications
    pending -> expired + jobs.status=expired, one commit.

    Idempotent: a retry finds the row no longer pending and changes nothing.
    """
    async with SessionLocal() as session:
        await JobRepository(session).expire_approval(job_id, reason)


@activity.defn
async def apply_job(job_id: int) -> ApplyResult:
    """Apply to an approved job behind the safety rails (see ApplyService).

    Settings are read here, never in the workflow: a changed env var must
    not change what a replayed workflow does.
    """
    async with SessionLocal() as session:
        service = ApplyService(
            repository=JobRepository(session),
            mode=settings.APPLY_MODE,
            max_per_day=settings.MAX_APPLIES_PER_DAY,
            answers_path=settings.ANSWERS_PATH,
            applier_factory=NaukriJobApplier,
        )
        return await service.apply(job_id)
