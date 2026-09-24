import structlog

from app.models.job import Job
from app.vector.embedder import Embedder
from app.vector.job_vector_store import JobVectorStore
from app.vector.texts import job_to_text, profile_to_text

logger = structlog.get_logger(__name__)

MIN_SCORE = 0.7


class JobRanker:
    """Picks the jobs closest in meaning to the candidate, using Qdrant."""

    def __init__(self, embedder: Embedder, store: JobVectorStore):
        self.embedder = embedder
        self.store = store

    def rank(self, candidate, jobs_with_ids: list[tuple[int, Job]], limit: int):
        """Return [(job, score)] for the best matching jobs, best first."""

        if not jobs_with_ids:
            return []

        self.store.create_collection_if_missing()

        job_by_id = {job_id: job for job_id, job in jobs_with_ids}

        # 1. Sync: make sure every job has a vector in Qdrant
        self._add_missing_vectors(job_by_id)

        # 2. Search: closest to the profile, but only among these jobs
        profile_vector = self.embedder.embed_one(profile_to_text(candidate))

        results = self.store.search(
            profile_vector,
            allowed_ids=list(job_by_id.keys()),
            limit=limit,
            min_score=MIN_SCORE,
        )

        # 3. Turn Qdrant IDs back into jobs
        ranked = [(job_by_id[job_id], score) for job_id, score, _ in results]

        logger.info(
            "jobs_ranked",
            candidates=len(job_by_id),
            selected=len(ranked),
            min_score=MIN_SCORE,
            top=[(job.title, round(score, 3)) for job, score in ranked],
        )

        return ranked

    def _add_missing_vectors(self, job_by_id: dict[int, Job]) -> None:
        missing_ids = self.store.find_missing_ids(list(job_by_id.keys()))

        if not missing_ids:
            return

        jobs = [job_by_id[job_id] for job_id in missing_ids]
        texts = [job_to_text(job.title, job.skills, job.description) for job in jobs]

        self.store.upsert_jobs(
            job_ids=missing_ids,
            vectors=self.embedder.embed(texts),
            payloads=[
                {"title": job.title, "company": job.company, "location": job.location}
                for job in jobs
            ],
        )