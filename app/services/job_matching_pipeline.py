from app.models.candidate_profile import CandidateProfile
from app.models.job_match_item import JobMatchItem
from app.services.job_discovery_service import JobDiscoveryService
from app.services.job_filter_service import JobFilterService
from app.services.job_match_level_service import JobMatchLevelService
from app.services.job_match_service import JobMatchService
from app.services.job_ranking_service import JobRankingService
from app.services.job_score_service import JobScoreService
import structlog
from app.db.job_repository import JobRepository
logger = structlog.get_logger(__name__)


class JobMatchingPipeline:

    def __init__(
        self,
        discovery_service: JobDiscoveryService,
        filter_service: JobFilterService,
        match_service: JobMatchService,
        score_service: JobScoreService,
        level_service: JobMatchLevelService,
        ranking_service: JobRankingService
    ):

        self.discovery_service = discovery_service
        self.filter_service = filter_service
        self.match_service = match_service
        self.score_service = score_service
        self.level_service = level_service
        self.ranking_service = ranking_service

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
        # 1b. Persist jobs, keep only new ones
        # --------------------------------------------

        if job_repository is not None:
            jobs = await job_repository.save_jobs(
                jobs,
                source="naukri"
            )

            logger.info(
                "new_jobs",
                count=len(jobs)
            )

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
        # 3. Select jobs for matching
        # --------------------------------------------

        selected_jobs = [
            job
            for job, matched_keywords in
            filtered_jobs[:max_match_jobs]
        ]

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

            result = await self.match_service.match(
                candidate_profile=candidate,
                job=job
            )

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