import pytest

from pipeline.embed import DIMENSIONS, QUERY_PREFIX, Embedder


class RecordingEmbedder(Embedder):
    def __init__(self):
        super().__init__()
        self.seen: list[list[str]] = []

    def embed_texts(self, texts):
        self.seen.append(list(texts))
        return [[0.0] * DIMENSIONS for _ in texts]


def test_embed_query_applies_bge_prefix():
    embedder = RecordingEmbedder()
    embedder.embed_query("What were net sales in 2024?")
    assert embedder.seen == [[QUERY_PREFIX + "What were net sales in 2024?"]]


@pytest.mark.slow
def test_real_model_embeds_at_384_dims_with_sane_similarity():
    embedder = Embedder()
    vectors = embedder.embed_texts(
        [
            "Total net sales increased during fiscal 2024.",
            "The weather in Paris is rainy in November.",
        ]
    )
    assert [len(v) for v in vectors] == [DIMENSIONS, DIMENSIONS]
    query = embedder.embed_query("How did revenue change in 2024?")

    def cosine(a, b):
        return sum(x * y for x, y in zip(a, b))  # fastembed vectors are L2-normalized

    assert cosine(query, vectors[0]) > cosine(query, vectors[1])
