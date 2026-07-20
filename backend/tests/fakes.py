import zlib

from pipeline.embed import DIMENSIONS


class FakeEmbedder:
    """Deterministic bag-of-words vectors: same text -> same vector, shared
    tokens -> nonzero cosine. embed_query applies no prefix, so a query equal
    to a stored chunk's text produces the identical vector (distance 0)."""

    def embed_texts(self, texts):
        return [self._vector(text) for text in texts]

    def embed_query(self, question):
        return self._vector(question)

    def _vector(self, text):
        vector = [0.0] * DIMENSIONS
        for token in text.lower().split():
            vector[zlib.crc32(token.encode()) % DIMENSIONS] += 1.0
        norm = sum(x * x for x in vector) ** 0.5 or 1.0
        return [x / norm for x in vector]
