from __future__ import annotations

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384


class Embedder:
    """Lazy wrapper around fastembed so importing this module stays cheap
    and tests that never embed stay offline."""

    def __init__(self, model_name: str = MODEL_NAME):
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._load().embed(texts)]

    def embed_query(self, question: str) -> list[float]:
        # BGE models need the query-side instruction prefix (design §4.4)
        return self.embed_texts([QUERY_PREFIX + question])[0]
