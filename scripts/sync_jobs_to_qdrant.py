import asyncio

from qdrant_client import QdrantClient
from sqlalchemy import select

from app.config import settings
from app.db.database import SessionLocal, engine
from app.db.models import JobRecord
from app.vector.embedder import Embedder
from app.vector.job_vector_store import JobVectorStore
from app.vector.texts import job_to_text


async def main():
    # 1. Read all jobs from PostgreSQL (the source of truth)
    async with SessionLocal() as session:
        result = await session.execute(select(JobRecord))
        jobs = result.scalars().all()

    await engine.dispose()
    print(f"Jobs in PostgreSQL: {len(jobs)}")

    if not jobs:
        return

    # 2. Make a report card for each job
    embedder = Embedder()
    texts = [
        job_to_text(job.title, job.skills, job.description)
        for job in jobs
    ]
    vectors = embedder.embed(texts)

    # 3. Store them in Qdrant, using the PostgreSQL id
    store = JobVectorStore(QdrantClient(url=settings.QDRANT_URL))
    store.create_collection_if_missing()
    store.upsert_jobs(
        job_ids=[job.id for job in jobs],
        vectors=vectors,
        payloads=[
            {"title": job.title, "company": job.company, "location": job.location}
            for job in jobs
        ],
    )

    print(f"Vectors in Qdrant: {store.count()}")


asyncio.run(main())