import sys

from qdrant_client import QdrantClient

from app.config import settings
from app.services.profile_loader import load_profile
from app.vector.embedder import Embedder
from app.vector.job_vector_store import JobVectorStore
from app.vector.texts import profile_to_text


def main():
    # Search with your own words if given, otherwise with your profile
    if len(sys.argv) > 1:
        query_text = " ".join(sys.argv[1:])
    else:
        candidate = load_profile(settings.PROFILE_PATH)
        query_text = profile_to_text(candidate)

    print(f"Searching for: {query_text}\n")

    embedder = Embedder()
    store = JobVectorStore(QdrantClient(url=settings.QDRANT_URL))

    results = store.search(embedder.embed_one(query_text), limit=5, min_score=0.07)

    if not results:
        print("No relevant jobs found.")

    for job_id, score, payload in results:
        print(f"{score:.3f}  [{job_id}] {payload['title']} | {payload['company']}")


main()