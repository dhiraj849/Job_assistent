import asyncio

from app.config import settings
from app.container import create_job_matching_pipeline
from app.models.candidate_profile import CandidateProfile
from app.logging_config import setup_logging

async def main():
    setup_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)
    # --------------------------------------------------
    # Candidate Profile
    # --------------------------------------------------

    candidate = CandidateProfile(
        name="Dhiraj Sharma",
        experience_years=4,
        skills=[
            "Python",
            "Django",
            "FastAPI",
            "PostgreSQL",
            "AWS",
            "Docker"
        ],
        education="Bachelor's in Mathematics"
    )

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

    ranked_jobs = await pipeline.run(
        candidate=candidate,
        max_match_jobs=settings.MAX_MATCH_JOBS
    )

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