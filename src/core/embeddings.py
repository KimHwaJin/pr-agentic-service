"""Embedding model for memory and workflow search.

EMBEDDING_PROVIDER: none (keyword fallback) | openai (gateway, OpenAI compatible) | mock.
The mock is a deterministic hashed character n-gram vector: no model server, but similar texts
still land close together, so the vector paths (pgvector index, Store search) run end to end.
"""

import hashlib
import math

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from core.config import Settings


class MockEmbeddings(Embeddings):
    def __init__(self, dims: int):
        self.dims = dims

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dims
        normalized = " ".join(text.lower().split())
        for n in (2, 3):
            for i in range(len(normalized) - n + 1):
                digest = hashlib.blake2b(normalized[i : i + n].encode(), digest_size=8).digest()
                index = int.from_bytes(digest[:4], "little") % self.dims
                vector[index] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)

    async def aembed_query(self, text: str) -> list[float]:
        return self.embed_query(text)


def build_embedder(settings: Settings) -> Embeddings | None:
    if settings.embedding_provider == "mock":
        return MockEmbeddings(settings.embedding_dims)
    if settings.embedding_provider == "openai":
        return OpenAIEmbeddings(
            model=settings.embedding_model,
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
            dimensions=settings.embedding_dims,
            check_embedding_ctx_length=False,
        )
    return None
