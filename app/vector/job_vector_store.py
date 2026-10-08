import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    Filter,
    HasIdCondition,
    PointStruct,
    VectorParams,
)

logger = structlog.get_logger(__name__)

# Named after the embedding model and the embedded text, so a change to
# either gets its own collection (scores across versions don't compare).
# v1: title + skills + card snippet. v2: title + skills + full JD when fetched.
COLLECTION = "jobs_bge_small_v2"
VECTOR_SIZE = 384


class JobVectorStore:
    """Everything about storing and searching job vectors in Qdrant."""

    def __init__(self, client: QdrantClient):
        self.client = client

    def create_collection_if_missing(self) -> None:
        if self.client.collection_exists(COLLECTION):
            return

        self.client.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        logger.info("qdrant_collection_created", collection=COLLECTION)

    def upsert_jobs(self, job_ids, vectors, payloads) -> None:
        points = []
        for job_id, vector, payload in zip(job_ids, vectors, payloads):
            points.append(PointStruct(id=job_id, vector=vector, payload=payload))

        self.client.upsert(collection_name=COLLECTION, points=points)
        logger.info("job_vectors_upserted", count=len(points))

    def find_missing_ids(self, job_ids) -> list[int]:
        """Which of these job IDs have no vector in Qdrant yet?"""
        found = self.client.retrieve(
            collection_name=COLLECTION,
            ids=job_ids,
            with_payload=False,
            with_vectors=False,
        )
        found_ids = {point.id for point in found}
        return [job_id for job_id in job_ids if job_id not in found_ids]

    def search(self, query_vector, allowed_ids=None, limit=5, min_score=None):
        """Return [(job_id, score, payload)] closest to query_vector."""
        query_filter = None
        if allowed_ids is not None:
            query_filter = Filter(must=[HasIdCondition(has_id=allowed_ids)])

        result = self.client.query_points(
            collection_name=COLLECTION,
            query=query_vector,
            query_filter=query_filter,
            limit=limit,
            score_threshold=min_score,
        )
        return [(point.id, point.score, point.payload) for point in result.points]

    def count(self) -> int:
        return self.client.count(collection_name=COLLECTION).count