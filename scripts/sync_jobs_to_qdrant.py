"""Re-embed every job in PostgreSQL into Qdrant (overwrites existing vectors).

Uses the full JD when the detail page was fetched, like the workflows do.
Usage: uv run python -m scripts.sync_jobs_to_qdrant
"""

import asyncio

from qdrant_client import QdrantClient

from app.config import settings
from app.db.database import SessionLocal, engine
from app.db.job_repository import JobRepository
from app.vector.embedder import Embedder
from app.vector.job_sync import upsert_job_vectors
from app.vector.job_vector_store import JobVectorStore


async def main():
    # 1. Read all jobs from PostgreSQL (the source of truth). Through the
    # repository, so description is the full JD when we have it, not the
    # card snippet (embedding the snippet would undo the detail fetch).
    async with SessionLocal() as session:
        jobs_with_ids = await JobRepository(session).get_all_jobs_with_ids()

    await engine.dispose()
    print(f"Jobs in PostgreSQL: {len(jobs_with_ids)}")

    if not jobs_with_ids:
        return

    # 2. Embed and store them in Qdrant, using the PostgreSQL id
    store = JobVectorStore(QdrantClient(url=settings.QDRANT_URL))
    store.create_collection_if_missing()
    upsert_job_vectors(Embedder(), store, dict(jobs_with_ids))

    print(f"Vectors in Qdrant: {store.count()}")


if __name__ == "__main__":
    asyncio.run(main())
