from fastembed import TextEmbedding

MODEL_NAME = "BAAI/bge-small-en-v1.5"


class Embedder:
    """Turns text into vectors (report cards)."""

    def __init__(self):
        self.model = TextEmbedding(MODEL_NAME)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self.model.embed(texts)]

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]