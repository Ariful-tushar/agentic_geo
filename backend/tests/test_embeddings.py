import math
from typing import Any

import pytest

from app.config import get_settings
from app.llm.cache import is_cacheable
from app.llm.embeddings import embed_texts, normalise


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def aembed_documents(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        assert kwargs["task_type"] in {"RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"}
        assert kwargs["output_dimensionality"] == get_settings().embedding_dim
        self.calls.append(texts)
        return [[3.0, 4.0] + [0.0] * 766 for _ in texts]


def test_normalise_gives_unit_length() -> None:
    vector = normalise([3.0, 4.0])
    assert math.isclose(sum(x * x for x in vector), 1.0)
    assert normalise([0.0, 0.0]) == [0.0, 0.0]


async def test_embeddings_are_768_numbers_normalised(
    no_db_logging: Any, memory_cache: dict[str, Any]
) -> None:
    vectors = await embed_texts(["a", "b"], "RETRIEVAL_DOCUMENT", client=FakeClient())  # type: ignore[arg-type]
    assert len(vectors) == 2
    assert len(vectors[0]) == 768
    assert math.isclose(sum(x * x for x in vectors[0]), 1.0)


async def test_cached_texts_are_not_sent_again(
    no_db_logging: Any, memory_cache: dict[str, Any]
) -> None:
    client = FakeClient()
    await embed_texts(["a"], "RETRIEVAL_QUERY", client=client)  # type: ignore[arg-type]
    await embed_texts(["a", "b"], "RETRIEVAL_QUERY", client=client)  # type: ignore[arg-type]
    assert client.calls == [["a"], ["b"]]


async def test_use_cache_false_always_calls_and_stores_nothing(
    no_db_logging: Any, memory_cache: dict[str, Any]
) -> None:
    client = FakeClient()
    for _ in range(2):
        await embed_texts(["a"], "RETRIEVAL_QUERY", client=client, use_cache=False)  # type: ignore[arg-type]
    assert len(client.calls) == 2
    assert memory_cache == {}


@pytest.mark.parametrize(("payload", "expected"), [({}, False), (None, False), ({"a": 1}, True)])
def test_empty_payloads_are_not_cacheable(payload: Any, expected: bool) -> None:
    assert is_cacheable(payload) is expected
