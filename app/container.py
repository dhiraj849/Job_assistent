from qdrant_client import QdrantClient

from app.config import settings
from app.job_sources.naukri import NaukriJobSource
from app.services.job_discovery_service import JobDiscoveryService
from app.services.job_filter_service import JobFilterService
from app.services.job_match_level_service import JobMatchLevelService
from app.services.job_match_service import JobMatchService
from app.services.job_matching_pipeline import JobMatchingPipeline
from app.services.job_ranker import JobRanker
from app.services.job_ranking_service import JobRankingService
from app.services.job_score_service import JobScoreService
from app.vector.embedder import Embedder
from app.vector.job_vector_store import JobVectorStore


def create_job_matching_pipeline(
    keyword: str,
    location: str
) -> JobMatchingPipeline:

    job_source = NaukriJobSource(
        keyword=keyword,
        location=location,
        headless=settings.BROWSER_HEADLESS,
        timeout_ms=settings.BROWSER_TIMEOUT_MS,
    )

    discovery_service = JobDiscoveryService(
        job_source=job_source
    )

    filter_service = JobFilterService()

    match_service = JobMatchService()

    score_service = JobScoreService()

    level_service = JobMatchLevelService()

    ranking_service = JobRankingService()

    # Embedder + Qdrant store go INSIDE the ranker
    ranker = JobRanker(
        embedder=Embedder(),
        store=JobVectorStore(QdrantClient(url=settings.QDRANT_URL)),
    )

    return JobMatchingPipeline(
        discovery_service=discovery_service,
        filter_service=filter_service,
        match_service=match_service,
        score_service=score_service,
        level_service=level_service,
        ranking_service=ranking_service,
        ranker=ranker,
    )