import structlog

from app.db.job_repository import JobRepository
from app.models.candidate_profile import CandidateProfile
from app.models.job_match_item import JobMatchItem
from app.services.job_discovery_service import JobDiscoveryService
from app.services.job_filter_service import JobFilterService
from app.services.job_match_level_service import JobMatchLevelService
from app.services.job_match_service import JobMatchService
from app.services.job_ranker import JobRanker
from app.services.job_ranking_service import JobRankingService
from app.services.job_score_service import JobScoreService

logger = structlog.get_logger(__name__)


class JobMatchingPipeline:

    def __init__(
        self,
        discovery_service: JobDiscoveryService,
        filter_service: JobFilterService,
        match_service: JobMatchService,
        score_service: JobScoreService,
        level_service: JobMatchLevelService,
        ranking_service: JobRankingService,
        ranker: JobRanker,
    ):

        self.discovery_service = discovery_service
        self.filter_service = filter_service
        self.match_service = match_service
        self.score_service = score_service
        self.level_service = level_service
        self.ranking_service = ranking_service
        self.ranker = ranker

    async def run(
        self,
        candidate: CandidateProfile,
        max_match_jobs: int = 5,
        job_repository: JobRepository | None = None
    ) -> list[JobMatchItem]:

        # --------------------------------------------
        # 1. Discover jobs
        # --------------------------------------------

        jobs = await self.discovery_service.get_jobs()

        logger.info(
            "jobs_discovered",
            count=len(jobs)
        )

        # --------------------------------------------
        # 1b. Persist jobs
        # --------------------------------------------

        if job_repository is not None:
            await job_repository.save_jobs(
                jobs,
                source="naukri"
            )

        # --------------------------------------------
        # 1c. Load all unmatched jobs from the database
        # --------------------------------------------

        if job_repository is not None:
            unmatched = await job_repository.get_unmatched_jobs_with_ids()

            job_id_by_url = {job.url: job_id for job_id, job in unmatched}

            jobs = [job for job_id, job in unmatched]

        # --------------------------------------------
        # 2. Filter jobs
        # --------------------------------------------

        filtered_jobs = self.filter_service.filter_jobs(
            jobs
        )

        logger.info(
            "jobs_filtered",
            count=len(filtered_jobs)
        )

        # --------------------------------------------
        # 3. Select jobs for matching (ranked by Qdrant)
        # --------------------------------------------

        # The filter returns (job, matched_keywords) pairs; keep only the jobs
        candidate_jobs = [job for job, matched_keywords in filtered_jobs]

        if job_repository is not None:

            # Qdrant needs each job's PostgreSQL id
            jobs_with_ids = [
                (job_id_by_url[job.url], job)
                for job in candidate_jobs
                if job.url in job_id_by_url
            ]

            ranked = self.ranker.rank(
                candidate,
                jobs_with_ids,
                limit=max_match_jobs
            )

            selected_jobs = [job for job, score in ranked]

        else:
            # No database: fall back to page order
            selected_jobs = candidate_jobs[:max_match_jobs]

        # --------------------------------------------
        # 4. Match jobs
        # --------------------------------------------

        matches = []

        for i, job in enumerate(
            selected_jobs,
            start=1
        ):

            job_logger = logger.bind(
                job_title=job.title,
                company=job.company
            )

            job_logger.info(
                "matching_started",
                index=i,
                total=len(selected_jobs)
            )

            try:
                result = await self.match_service.match(
                    candidate_profile=candidate,
                    job=job
                )
            except Exception:
                job_logger.warning(
                    "matching_failed",
                    exc_info=True
                )
                continue

            # ----------------------------------------
            # 5. Calculate overall score
            # ----------------------------------------

            overall_score = self.score_service.calculate(
                skill_match=result.skill_match,
                role_match=result.role_match,
                experience_match=result.experience_match
            )

            # ----------------------------------------
            # 6. Calculate match level
            # ----------------------------------------

            match_level = self.level_service.classify(
                overall_score
            )

            if job_repository is not None:
                await job_repository.save_match(
                    job_id_by_url[job.url],
                    result,
                    overall_score,
                    match_level
                )

            # ----------------------------------------
            # 7. Create match item
            # ----------------------------------------

            match_item = JobMatchItem(
                job=job,
                match=result,
                overall_score=overall_score,
                match_level=match_level
            )

            matches.append(match_item)

            job_logger.info(
                "matching_finished",
                overall_score=overall_score,
                match_level=match_level
            )

        # --------------------------------------------
        # 8. Rank jobs
        # --------------------------------------------

        ranked_jobs = self.ranking_service.rank(
            matches
        )

        return ranked_jobs