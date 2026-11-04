from core.config import Settings
from core.embeddings import build_embedder


def _settings(**kw):
    return Settings(
        embedding_provider="openai",
        embedding_base_url="http://gateway/v1",
        embedding_model="bge-m3",
        **kw,
    )


def test_dimensions_not_sent_by_default():
    # vLLM/TEI serving bge-m3 answer 400 to any `dimensions`
    assert build_embedder(_settings()).dimensions is None


def test_dimensions_sent_when_enabled():
    embedder = build_embedder(
        _settings(embedding_send_dimensions=True, embedding_dims=512)
    )
    assert embedder.dimensions == 512
