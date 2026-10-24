"""The FAQ agent (SPEC 8.4): extraction, dedupe, relevance, grounded drafts, resume, dev mode.

Fake pages, a fake AI, fake embeddings and a fake knowledge base: nothing here calls a real AI or
the internet.
"""

import json
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.faq.graph import FaqResult, run_faq
from app.agents.faq.nodes import FaqDeps, normalise_question
from app.db.models import Company, FaqDraft, PublicQuestion
from app.fetch.extract import extract
from app.fetch.fetcher import FetchResult
from app.llm.internal import InternalAIError
from app.llm.limits import DailyStop
from app.schemas.agents import ExtractedQuestions, FaqDraftOut, RelevanceVerdicts
from tests.api_helpers import Api, api, seeded  # noqa: F401
from tests.ax_helpers import FakeKb
from tests.conftest import DbCall
from tests.kb_helpers import FakeEmbeddings, import_kemira

PAGE = "https://demo.example.org/public-questions.html"
Q_COAGULANT = "Which company makes coagulants for wastewater treatment in Finland?"
Q_BIO = "Are there bio-based alternatives to fossil polymers for water treatment?"
Q_PIZZA = "What is the best pizza place in Helsinki?"
Q_PHOSPHORUS = "How do municipal plants remove phosphorus from wastewater?"
QUESTIONS = [Q_COAGULANT, Q_BIO, Q_PIZZA, Q_PHOSPHORUS]
CHUNK_URL = "https://www.kemira.com/company/"
ANSWER = (
    "Kemira is a Finnish chemicals company that supplies coagulants and other water treatment "
    "chemicals to municipal and industrial customers. Its products help plants remove "
    "phosphorus, solids and organic matter from wastewater, and the company develops new "
    "solutions together with its customers. Kemira also works with sustainability goals in "
    "mind. You can find more details about Kemira's water treatment offering on the "
    "company website."
)


class QuestionPages:
    """The polite fetcher: serves `FetchResult`s from a dict, 404 for everything else."""

    def __init__(self) -> None:
        self.pages: dict[str, FetchResult] = {}
        self.fetched: list[tuple[str, bool]] = []

    def set_questions(self, questions: list[str], url: str = PAGE) -> None:
        self.pages[url] = FetchResult(
            url, "ok", http_status=200, text="\n".join(questions), questions=list(questions)
        )

    def set_text(self, text: str, url: str = PAGE) -> None:
        self.pages[url] = FetchResult(url, "ok", http_status=200, text=text)

    async def fetch(self, session: Any, url: str, *, force: bool = False) -> FetchResult:
        self.fetched.append((url, force))
        return self.pages.get(url) or FetchResult(url, "http_error", http_status=404)

    async def aclose(self) -> None:
        return None


class FakeFaqAi:
    """Answers the extract, relevance and draft roles; records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []  # (schema name, prompt)
        self.extracted: list[str] = []
        self.draft: FaqDraftOut | None = None  # None = a good draft
        self.errors: dict[str, Exception] = {}  # schema name -> raised

    def count(self, schema: str) -> int:
        return sum(1 for name, _ in self.calls if name == schema)

    async def __call__(self, role: str, prompt: str, schema: type, **kwargs: Any) -> Any:
        self.calls.append((schema.__name__, prompt))
        if error := self.errors.get(schema.__name__):
            raise error
        if schema is ExtractedQuestions:
            return ExtractedQuestions(questions=self.extracted)
        if schema is RelevanceVerdicts:
            listing = json.loads(prompt.split("QUESTIONS:\n", 1)[1])
            return RelevanceVerdicts.model_validate(
                {
                    "items": [
                        {
                            "code": item["code"],
                            "relevant": "pizza" not in item["question"],
                            "reason": "Not about water chemistry"
                            if "pizza" in item["question"]
                            else "About water treatment",
                        }
                        for item in listing
                    ]
                }
            )
        if schema is FaqDraftOut:
            if "phosphorus" in prompt.rsplit("QUESTION:", 1)[1]:
                return FaqDraftOut(answerable=False)
            return self.draft or FaqDraftOut(
                answerable=True, answer=ANSWER, source_urls=[CHUNK_URL]
            )
        raise AssertionError(f"unexpected schema {schema}")


class Setup:
    def __init__(self) -> None:
        self.pages = QuestionPages()
        self.ai = FakeFaqAi()
        self.kb = FakeKb([(CHUNK_URL, "Kemira supplies coagulants for water treatment.")])
        self.embeddings = FakeEmbeddings()


@pytest.fixture
def world() -> Setup:
    return Setup()


def faq(db: DbCall, world: Setup, mode: str = "live") -> FaqResult:
    async def go(session: AsyncSession) -> FaqResult:
        if await session.scalar(select(func.count()).select_from(Company)) == 0:
            await import_kemira(session)
            await session.execute(update(Company).values(faq_source_urls=[PAGE]))
            await session.commit()
        deps = FaqDeps(
            sessionmaker=async_sessionmaker(session.bind, expire_on_commit=False),  # type: ignore[arg-type]
            llm=world.ai,
            fetcher=world.pages,
            embed=world.embeddings.aembed_documents,
            kb_search=world.kb,
        )
        return await run_faq(deps, "kemira", mode=mode)

    return db(go)


def stored(db: DbCall) -> tuple[list[PublicQuestion], list[FaqDraft]]:
    async def go(session: AsyncSession) -> tuple[list[PublicQuestion], list[FaqDraft]]:
        questions = (
            await session.scalars(select(PublicQuestion).order_by(PublicQuestion.text))
        ).all()
        drafts = (await session.scalars(select(FaqDraft).order_by(FaqDraft.question))).all()
        return list(questions), list(drafts)

    return db(go)


# ---- extraction ------------------------------------------------------------------------------


def test_the_extractor_finds_the_elements_with_class_question() -> None:
    html = (
        "<html><body><ul><li><time>1 Oct</time><span class='question'> What is  a  "
        "coagulant? </span></li><li><span class='question about'>Who makes it?</span></li>"
        "<li>No question here</li></ul></body></html>"
    )
    assert extract(html).questions == ["What is a coagulant?", "Who makes it?"]
    assert extract("<html><body><p>Hi</p></body></html>").questions == []


def test_questions_come_from_class_question_without_an_ai_call(db: DbCall, world: Setup) -> None:
    world.pages.set_questions(QUESTIONS)
    result = faq(db, world)
    assert world.ai.count("ExtractedQuestions") == 0
    assert (result.found, result.new, result.duplicates) == (4, 4, 0)
    assert world.pages.fetched == [(PAGE, True)]  # always a forced, fresh download
    questions, _ = stored(db)
    assert {q.text for q in questions} == set(QUESTIONS)
    assert all(q.source_url == PAGE for q in questions)


def test_a_page_without_class_question_falls_back_to_the_ai_and_drops_invented_ones(
    db: DbCall, world: Setup
) -> None:
    world.pages.set_text(f"Welcome.\n{Q_BIO}\nOur forum rules are below.")
    world.ai.extracted = [Q_BIO, "Is this question really on the page at all?"]
    result = faq(db, world)
    assert world.ai.count("ExtractedQuestions") == 1
    assert (result.found, result.new) == (1, 1)
    questions, _ = stored(db)
    assert [q.text for q in questions] == [Q_BIO]


# ---- dedupe ----------------------------------------------------------------------------------


def test_normalising_lowercases_trims_and_drops_punctuation() -> None:
    assert normalise_question("  Who IS Kemira's CEO?? ") == "who is kemira s ceo"
    assert normalise_question("Who is Kemira’s CEO?") == normalise_question("who is kemira’s ceo")


def test_a_second_run_adds_nothing_that_exists(db: DbCall, world: Setup) -> None:
    world.pages.set_questions(QUESTIONS)
    faq(db, world)
    before = stored(db)
    relevance_calls = world.ai.count("RelevanceVerdicts")
    again = faq(db, world)
    after = stored(db)
    assert (again.found, again.new, again.duplicates, again.drafts) == (4, 0, 4, 0)
    assert [q.id for q in after[0]] == [q.id for q in before[0]]
    assert [d.id for d in after[1]] == [d.id for d in before[1]]
    assert world.ai.count("RelevanceVerdicts") == relevance_calls  # no new questions, no AI call


def test_only_the_new_question_is_added(db: DbCall, world: Setup) -> None:
    world.pages.set_questions(QUESTIONS)
    faq(db, world)
    new = "Which Finnish chemical companies are listed on Nasdaq Helsinki?"
    world.pages.set_questions([new, *QUESTIONS])
    result = faq(db, world)
    assert (result.found, result.new, result.duplicates) == (5, 1, 4)
    assert [v.candidate.text for v in result.verdicts] == [new]
    questions, drafts = stored(db)
    assert len(questions) == 5 and len(drafts) == 3  # coagulant, bio and the new one


def test_a_question_that_differs_only_in_case_or_punctuation_is_a_duplicate(
    db: DbCall, world: Setup
) -> None:
    world.pages.set_questions([Q_BIO])
    faq(db, world)
    world.pages.set_questions([Q_BIO.upper().rstrip("?") + " ??"])
    result = faq(db, world)
    assert (result.new, result.duplicates) == (0, 1)
    assert len(stored(db)[0]) == 1


def test_near_duplicates_are_skipped_by_embedding_similarity(db: DbCall, world: Setup) -> None:
    world.pages.set_questions([Q_COAGULANT])
    faq(db, world)
    near = "Which company makes coagulants for wastewater treatment in Finland today?"
    other = Q_BIO
    world.pages.set_questions([near, other])
    result = faq(db, world)
    assert [v.candidate.text for v in result.verdicts] == [other]
    assert result.duplicates == 1
    # also inside one batch: the second of two near-identical new questions is dropped
    world.pages.set_questions(
        [Q_PHOSPHORUS, Q_PHOSPHORUS.replace("wastewater?", "wastewater today?")]
    )
    result = faq(db, world)
    assert len(result.verdicts) == 1


# ---- relevance and drafts --------------------------------------------------------------------


def test_relevance_is_stored_with_a_reason_and_only_relevant_questions_get_drafts(
    db: DbCall, world: Setup
) -> None:
    world.pages.set_questions(QUESTIONS)
    result = faq(db, world)
    assert world.ai.count("RelevanceVerdicts") == 1  # one call for all new questions
    assert (result.relevant, result.drafts, result.unanswerable) == (3, 2, 1)
    questions, drafts = stored(db)
    by_text = {q.text: q for q in questions}
    assert by_text[Q_PIZZA].relevant is False
    assert by_text[Q_PIZZA].relevance_reason == "Not about water chemistry"
    assert by_text[Q_BIO].relevant is True
    assert {d.question for d in drafts} == {Q_COAGULANT, Q_BIO}
    assert drafts[0].answer == ANSWER and drafts[0].source_urls == [CHUNK_URL]


def test_the_draft_prompt_contains_only_company_information(db: DbCall, world: Setup) -> None:
    world.pages.set_questions([Q_BIO])
    faq(db, world)
    prompt = next(p for name, p in world.ai.calls if name == "FaqDraftOut")
    assert "Kemira supplies coagulants for water treatment." in prompt  # the RAG chunk
    assert "ONLY the text chunks" in prompt and "Antti Salminen" in prompt  # expected answers
    assert world.kb.queries == [Q_BIO]


def test_a_draft_must_name_the_company_and_cite_a_known_source(db: DbCall, world: Setup) -> None:
    world.pages.set_questions([Q_BIO])
    no_name = ANSWER.replace("Kemira", "The firm")
    world.ai.draft = FaqDraftOut(answerable=True, answer=no_name, source_urls=[CHUNK_URL])
    result = faq(db, world)
    assert world.ai.count("FaqDraftOut") == 2  # one retry with the reason appended
    assert (result.drafts, result.unanswerable) == (0, 1) and stored(db)[1] == []

    world.ai.draft = FaqDraftOut(
        answerable=True, answer=ANSWER, source_urls=["https://invented.example.com/page"]
    )
    assert faq(db, world).drafts == 0  # a source that was not in the chunks does not count


def test_unknown_source_urls_are_removed_from_a_draft(db: DbCall, world: Setup) -> None:
    world.pages.set_questions([Q_BIO])
    world.ai.draft = FaqDraftOut(
        answerable=True,
        answer=ANSWER,
        source_urls=["https://invented.example.com/x", CHUNK_URL, CHUNK_URL],
    )
    faq(db, world)
    assert stored(db)[1][0].source_urls == [CHUNK_URL]


def test_the_draft_schema_enforces_60_to_120_words() -> None:
    with pytest.raises(ValidationError, match="words"):
        FaqDraftOut(answerable=True, answer="Too short to be a real FAQ answer.")
    with pytest.raises(ValidationError, match="words"):
        FaqDraftOut(answerable=True, answer="word " * 130)
    assert FaqDraftOut(answerable=False).answer == ""
    assert len(FaqDraftOut(answerable=True, answer=ANSWER).answer.split()) in range(60, 121)


# ---- stops, failures, resume -----------------------------------------------------------------


def test_a_stopped_ai_during_relevance_stores_nothing_and_the_next_run_finishes(
    db: DbCall, world: Setup
) -> None:
    world.pages.set_questions([Q_COAGULANT, Q_BIO])
    world.ai.errors["RelevanceVerdicts"] = DailyStop("gemini", 7200)
    first = faq(db, world)
    assert first.status == "partial" and first.new == 0 and stored(db) == ([], [])
    world.ai.errors.clear()
    second = faq(db, world)
    assert (second.status, second.new, second.drafts) == ("completed", 2, 2)


def test_a_stopped_ai_during_drafts_keeps_the_questions_and_the_next_run_adds_the_drafts(
    db: DbCall, world: Setup
) -> None:
    world.pages.set_questions([Q_COAGULANT, Q_BIO])
    world.ai.errors["FaqDraftOut"] = InternalAIError("provider down")
    first = faq(db, world)
    questions, drafts = stored(db)
    assert first.status == "partial" and len(questions) == 2 and drafts == []
    world.ai.errors.clear()
    second = faq(db, world)
    assert (second.new, second.drafts, second.status) == (0, 2, "completed")
    assert len(stored(db)[0]) == 2 and len(stored(db)[1]) == 2


def test_a_temporary_page_failure_is_partial_and_a_404_is_only_a_warning(
    db: DbCall, world: Setup
) -> None:
    world.pages.pages[PAGE] = FetchResult(PAGE, "http_error", http_status=503)
    result = faq(db, world)
    assert result.status == "partial" and any("503" in w for w in result.warnings)
    world.pages.pages[PAGE] = FetchResult(PAGE, "http_error", http_status=404)
    result = faq(db, world)
    assert result.status == "completed" and any("404" in w for w in result.warnings)
    assert stored(db) == ([], [])


# ---- dev mode --------------------------------------------------------------------------------


def test_dev_mode_stores_nothing_and_looks_at_the_first_four_new_questions(
    db: DbCall, world: Setup
) -> None:
    extra = [f"Is there a seventh water treatment question number {n} here?" for n in range(3)]
    world.pages.set_questions([*QUESTIONS, *extra])
    result = faq(db, world, mode="dev")
    assert result.mode == "dev" and result.new == 4 and result.found == 7
    assert result.relevant == 3 and result.drafts == 2 and not result.draft_list[0].stored

    async def counts(session: AsyncSession) -> tuple[int, int]:
        q = await session.scalar(select(func.count()).select_from(PublicQuestion))
        d = await session.scalar(select(func.count()).select_from(FaqDraft))
        return q or 0, d or 0

    assert db(counts) == (0, 0)


# ---- API -------------------------------------------------------------------------------------


async def seed_faq(session: AsyncSession) -> None:
    question = PublicQuestion(
        company_id="kemira",
        source_url=PAGE,
        text=Q_BIO,
        normalized=normalise_question(Q_BIO),
        relevant=True,
        relevance_reason="About water treatment",
    )
    off_topic = PublicQuestion(
        company_id="kemira",
        source_url=PAGE,
        text=Q_PIZZA,
        normalized=normalise_question(Q_PIZZA),
        relevant=False,
        relevance_reason="Not about water chemistry",
    )
    session.add_all([question, off_topic])
    await session.flush()
    session.add(
        FaqDraft(
            company_id="kemira",
            public_question_id=question.id,
            question=Q_BIO,
            answer=ANSWER,
            source_urls=[CHUNK_URL],
        )
    )
    await session.commit()


def test_the_faq_endpoints_are_public_and_return_questions_and_drafts(api: Api) -> None:
    seeded(api)
    api.with_session(seed_faq)
    questions = api.get("/api/companies/kemira/faq/questions").json()
    assert {q["text"] for q in questions} == {Q_BIO, Q_PIZZA}
    pizza = next(q for q in questions if q["text"] == Q_PIZZA)
    assert pizza["relevant"] is False and pizza["relevance_reason"] == "Not about water chemistry"
    assert pizza["source_url"] == PAGE and pizza["first_seen_at"]
    (draft,) = api.get("/api/companies/kemira/faq/drafts").json()
    assert draft["question"] == Q_BIO and draft["answer"] == ANSWER
    assert draft["source_urls"] == [CHUNK_URL]


@pytest.mark.parametrize("part", ["questions", "drafts"])
def test_the_faq_endpoints_404_for_an_unknown_company(api: Api, part: str) -> None:
    assert api.get(f"/api/companies/nope/faq/{part}").status_code == 404
    seeded(api)
    assert api.get(f"/api/companies/kemira/faq/{part}").json() == []
