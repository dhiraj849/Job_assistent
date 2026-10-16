"""Write job vectors to Qdrant: the one place that decides what we embed."""

from app.models.job import Job
from app.vector.embedder import Embedder
from app.vector.job_vector_store import JobVectorStore
from app.vector.texts import job_to_text


def upsert_job_vectors(embedder: Embedder, store: JobVectorStore, jobs_by_id: dict[int, Job]) -> None:
    """Embed these jobs and write their vectors (overwrites existing points).

    Pass Job DTOs from the repository: their description is the full JD when
    it was fetched, else the snippet (see JobRepository._to_job).
    """
    if not jobs_by_id:
        return

    ids = list(jobs_by_id)
    jobs = list(jobs_by_id.values())
    store.upsert_jobs(
        job_ids=ids,
        vectors=embedder.embed([job_to_text(job.title, job.skills, job.description) for job in jobs]),
        payloads=[{"title": job.title, "company": job.company, "location": job.location} for job in jobs],
    )
