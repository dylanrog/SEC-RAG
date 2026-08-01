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


class StubGenerator:
    """Replays a canned response in small deltas -- exercises the streaming
    split without an API key or a cent of spend (design §9). Successive calls
    advance through `responses`, then repeat the last one."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    def stream(self, system, user):
        self.calls += 1
        index = min(self.calls - 1, len(self.responses) - 1)
        text = self.responses[index]
        for start in range(0, len(text), 7):
            yield text[start : start + 7]
