"""768-dimension, normalised Gemini embeddings (SPEC 7.4), cached per text.

LangChain's GoogleGenerativeAIEmbeddings accepts `output_dimensionality` and `task_type`
(checked in langchain_google_genai 4.4.2 embeddings.py), so no custom wrapper around
google-genai is needed. We only add normalising, caching, limits and logging.
"""

import math
import time
from typing import Literal

from langchain_core.embeddings import Embeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from app.config import get_settings
from app.llm.cache import cache_get, cache_set
from app.llm.limits import call_with_retries
from app.llm.usage import log_call, make_hash

TaskType = Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"]
BATCH_SIZE = 50


def normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else vector


def _client() -> GoogleGenerativeAIEmbeddings:
    settings = get_settings()
    return GoogleGenerativeAIEmbeddings(
        model=settings.gemini_embed_model,
        google_api_key=settings.gemini_api_key,
        output_dimensionality=settings.embedding_dim,
    )


def _key(text: str, task_type: str) -> str:
    settings = get_settings()
    return make_hash(
        "embedding", settings.gemini_embed_model, str(settings.embedding_dim), task_type, text
    )


async def embed_texts(
    texts: list[str],
    task_type: TaskType,
    client: GoogleGenerativeAIEmbeddings | None = None,
    use_cache: bool = True,
) -> list[list[float]]:
    """Embed in batches; texts already in llm_cache are not sent again."""
    settings = get_settings()
    vectors: dict[int, list[float]] = {}
    missing: list[int] = []
    for i, text in enumerate(texts):
        hit = await cache_get(_key(text, task_type)) if use_cache else None
        if hit:
            vectors[i] = hit["vector"]
        else:
            missing.append(i)
    if missing and client is None:
        client = _client()
    for start in range(0, len(missing), BATCH_SIZE):
        batch = missing[start : start + BATCH_SIZE]
        started = time.monotonic()
        raw = await call_with_retries(
            "gemini",
            lambda b=batch: client.aembed_documents(
                [texts[i] for i in b],
                task_type=task_type,
                output_dimensionality=settings.embedding_dim,
            ),
        )
        await log_call(
            role="embedding",
            provider="gemini",
            model=settings.gemini_embed_model,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        for i, vector in zip(batch, raw, strict=True):
            vectors[i] = normalise(vector)
            if use_cache:
                await cache_set(
                    _key(texts[i], task_type),
                    "gemini",
                    settings.gemini_embed_model,
                    {"vector": vectors[i]},
                )
    return [vectors[i] for i in range(len(texts))]


class GeminiEmbeddings(Embeddings):
    """LangChain Embeddings for PGVector (async methods; used from D2.1)."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("use aembed_documents (async only)")

    def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError("use aembed_query (async only)")

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return await embed_texts(texts, "RETRIEVAL_DOCUMENT")

    async def aembed_query(self, text: str) -> list[float]:
        return (await embed_texts([text], "RETRIEVAL_QUERY"))[0]
