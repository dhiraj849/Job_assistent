from app.job_sources.naukri import NaukriJobSource
from app.services.job_discovery_service import JobDiscoveryService
from app.services.job_filter_service import JobFilterService
from app.services.job_match_level_service import JobMatchLevelService
from app.services.job_match_service import JobMatchService
from app.services.job_ranking_service import JobRankingService
from app.services.job_score_service import JobScoreService
from app.services.job_matching_pipeline import JobMatchingPipeline


def create_job_matching_pipeline(
    keyword: str,
    location: str
) -> JobMatchingPipeline:

    job_source = NaukriJobSource(
        keyword=keyword,
        location=location
    )

    discovery_service = JobDiscoveryService(
        job_source=job_source
    )

    filter_service = JobFilterService()

    match_service = JobMatchService()

    score_service = JobScoreService()

    level_service = JobMatchLevelService()

    ranking_service = JobRankingService()

    return JobMatchingPipeline(
        discovery_service=discovery_service,
        filter_service=filter_service,
        match_service=match_service,
        score_service=score_service,
        level_service=level_service,
        ranking_service=ranking_service
    )