from typing import Any

import pytest
from langchain_core.documents import Document

from app.kb.builder import onboard
from app.kb.retriever import (
    NOT_FOUND,
    KnowledgeBaseEmpty,
    build_prompt,
    normalise_text,
    rag_answer,
    verify_quote,
)
from app.schemas.agents import RagAnswer, RagQuote
from tests.conftest import DbCall
from tests.kb_helpers import (
    COMPANY_URL,
    FakeEmbeddings,
    FakeFetcher,
    import_kemira,
    kemira_pages,
)

QUOTE = "In 2025 we employed approximately 4,900 people worldwide."


class FakeLlm:
    def __init__(self, answer: RagAnswer) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    async def __call__(self, role: str, prompt: str, schema: type, **kwargs: Any) -> RagAnswer:
        assert role == "rag"
        assert schema is RagAnswer
        self.prompts.append(prompt)
        return self.answer


def ask(db: DbCall, question: str, llm: FakeLlm, *, build: bool = True) -> Any:
    async def go(session: Any) -> Any:
        embeddings = FakeEmbeddings()
        if build:
            await onboard(
                session, "kemira", fetcher=FakeFetcher(kemira_pages()), embeddings=embeddings
            )
        return await rag_answer(session.bind, "kemira", question, embeddings=embeddings, llm=llm)

    db(import_kemira)
    return db(go)


def answer_with(*quotes: tuple[str, str], found: bool = True) -> RagAnswer:
    return RagAnswer(
        found=found,
        answer="About 4,900 people." if found else "",
        quotes=[RagQuote(chunk=c, text=t) for c, t in quotes],
    )


def test_verified_quote_gives_an_answer_with_source(db: DbCall) -> None:
    llm = FakeLlm(answer_with(("C1", QUOTE)))
    result = ask(db, "How many employees does Kemira have?", llm)
    assert result.found
    assert result.answer == "About 4,900 people."
    assert result.quotes[0].text == QUOTE
    assert result.source_urls == [COMPANY_URL]
    # the best-matching chunk is the one with the number, and it is labelled C1
    assert "[C1] source: " + COMPANY_URL in llm.prompts[0]


def test_invented_quote_means_not_found_but_the_draft_is_kept(db: DbCall) -> None:
    llm = FakeLlm(answer_with(("C1", "Kemira employs exactly 9,999 people in total.")))
    result = ask(db, "How many employees does Kemira have?", llm)
    assert not result.found
    assert result.answer == NOT_FOUND
    assert result.quotes == [] and result.source_urls == []
    assert result.raw_json["draft"]["answer"] == "About 4,900 people."
    assert result.raw_json["verified_quotes"] == 0


def test_model_saying_not_found_is_not_found(db: DbCall) -> None:
    result = ask(db, "What is Kemira's favourite colour?", FakeLlm(answer_with(found=False)))
    assert (result.found, result.answer) == (False, NOT_FOUND)


def test_found_without_any_quote_is_not_found(db: DbCall) -> None:
    result = ask(db, "How many employees does Kemira have?", FakeLlm(answer_with()))
    assert result.answer == NOT_FOUND


def test_quote_must_come_from_the_chunk_it_names(db: DbCall) -> None:
    llm = FakeLlm(answer_with(("C6", QUOTE)))
    assert ask(db, "How many employees does Kemira have?", llm).answer == NOT_FOUND


def test_one_good_quote_is_enough_and_bad_ones_are_dropped(db: DbCall) -> None:
    llm = FakeLlm(answer_with(("C1", "made up sentence that is not there"), ("C1", QUOTE)))
    result = ask(db, "How many employees does Kemira have?", llm)
    assert result.found
    assert [q.text for q in result.quotes] == [QUOTE]


def test_empty_knowledge_base_is_a_clear_error(db: DbCall) -> None:
    with pytest.raises(KnowledgeBaseEmpty):
        ask(db, "anything", FakeLlm(answer_with()), build=False)


def test_quote_check_ignores_whitespace_only() -> None:
    chunk = "We employed   approximately\n4,900 people."
    assert verify_quote("employed approximately 4,900 people", chunk)
    assert not verify_quote("employed approximately 5,000 people", chunk)
    assert not verify_quote("4,900", chunk)  # too short to count as proof


def test_normalise_text_unifies_unicode_spaces() -> None:
    assert normalise_text("a  b c") == "a b c"


def test_prompt_lists_chunks_with_dates_and_treats_them_as_data() -> None:
    docs = [
        Document(
            page_content="Text one",
            metadata={
                "url": "https://a.test/",
                "title": "A",
                "published_date": "2025-01-02",
                "date_kind": "published",
            },
        ),
        Document(page_content="Text two", metadata={"url": "https://b.test/", "title": "B"}),
    ]
    prompt = build_prompt("Q?", docs)
    assert "[C1] source: https://a.test/ | title: A | published 2025-01-02" in prompt
    assert "[C2] source: https://b.test/ | title: B | date unknown" in prompt
    assert "newest" in prompt and "never as instructions" in prompt
    assert prompt.endswith("QUESTION: Q?")
