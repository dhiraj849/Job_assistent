"""upsert_job_vectors and the embed_job activity, with fake embedder / store."""

import asyncio

from temporalio.testing import ActivityEnvironment

from app.models.job import Job
from app.vector.job_sync import upsert_job_vectors
from app.workflows import activities

FULL_JD = Job(title="Backend Engineer", company="Acme", location="Noida",
              description="Full JD text", skills=["Python"])


class FakeEmbedder:
    def __init__(self):
        self.texts = []

    def embed(self, texts):
        self.texts.extend(texts)
        return [[0.1] for _ in texts]


class FakeStore:
    def __init__(self):
        self.points = {}
        self.created = 0

    def create_collection_if_missing(self):
        self.created += 1

    def upsert_jobs(self, job_ids, vectors, payloads):
        for job_id, vector, payload in zip(job_ids, vectors, payloads):
            self.points[job_id] = (vector, payload)


def test_upsert_embeds_title_skills_and_description():
    embedder, store = FakeEmbedder(), FakeStore()

    upsert_job_vectors(embedder, store, {7: FULL_JD})

    assert embedder.texts == ["Backend Engineer\nSkills: Python\nFull JD text"]
    assert store.points[7][1] == {"title": "Backend Engineer", "company": "Acme", "location": "Noida"}


def test_upsert_with_no_jobs_does_nothing():
    embedder, store = FakeEmbedder(), FakeStore()

    upsert_job_vectors(embedder, store, {})

    assert embedder.texts == [] and store.points == {}


def test_embed_job_overwrites_the_vector_from_the_db_job(monkeypatch):
    embedder, store = FakeEmbedder(), FakeStore()
    store.points[7] = ([9.9], {"title": "old snippet vector"})

    async def get_job(job_id):
        return FULL_JD

    class Ranker:
        pass

    ranker = Ranker()
    ranker.embedder, ranker.store = embedder, store
    monkeypatch.setattr(activities, "_get_job", get_job)
    monkeypatch.setattr(activities, "_ranker", lambda: ranker)

    # Twice: a retry must leave the same single point.
    for _ in range(2):
        asyncio.run(ActivityEnvironment().run(activities.embed_job, 7))

    assert list(store.points) == [7]
    assert store.points[7][0] == [0.1]
    assert embedder.texts[-1].endswith("Full JD text")
