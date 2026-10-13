from langchain_openai import OpenAIEmbeddings

from core.config import Settings


def build_embedder(settings: Settings) -> OpenAIEmbeddings | None:
    """Gateway embedding model (OpenAI compatible). None disables semantic search."""
    if not settings.embeddings_enabled:
        return None
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key,
        dimensions=settings.embedding_dims,
        check_embedding_ctx_length=False,
    )
