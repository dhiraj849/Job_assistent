import asyncio

import structlog

from app.config import settings
from app.container import create_job_matching_pipeline
from app.logging_config import setup_logging
from app.services.profile_loader import load_profile
from app.db.database import SessionLocal, engine
from app.db.job_repository import JobRepository
# from app.db.job_repository import JobRepository

logger = structlog.get_logger(__name__)


async def main():
    setup_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)
    # --------------------------------------------------
    # Candidate Profile
    # --------------------------------------------------

    candidate = load_profile(settings.PROFILE_PATH)
    logger.info("profile_loaded", name=candidate.name, skills=len(candidate.skills))
    # --------------------------------------------------
    # Create Job Matching Pipeline
    # --------------------------------------------------

    pipeline = create_job_matching_pipeline(
        keyword=settings.JOB_SEARCH_KEYWORD,
        location=settings.JOB_SEARCH_LOCATION
    )

    # --------------------------------------------------
    # Run Pipeline
    # --------------------------------------------------

    async with SessionLocal() as session:
        ranked_jobs = await pipeline.run(
            candidate=candidate,
            max_match_jobs=settings.MAX_MATCH_JOBS,
            job_repository=JobRepository(session),
        )

    await engine.dispose()
    if not ranked_jobs:
        print("\nNo matching jobs found. Try a different keyword or location.")
        return
    # --------------------------------------------------
    # Display Final Ranking
    # --------------------------------------------------

    print("\n===== FINAL RANKING =====")

    for i, item in enumerate(
        ranked_jobs,
        start=1
    ):

        print(
            f"\n{i}. {item.job.title}"
        )

        print(
            f"   Company: "
            f"{item.job.company}"
        )

        print(
            f"   Overall Score: "
            f"{item.overall_score}"
        )

        print(
            f"   Match Level: "
            f"{item.match_level}"
        )

        print(
            f"   Recommendation: "
            f"{item.match.recommendation}"
        )


if __name__ == "__main__":

    asyncio.run(main())