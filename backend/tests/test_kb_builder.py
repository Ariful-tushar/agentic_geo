from typing import Any

from sqlalchemy import select, text, update

from app.db.models import Company, KnowledgeSource
from app.kb.builder import (
    CHUNK_SIZE,
    OnboardResult,
    chunk_id,
    chunk_text,
    onboard,
)
from tests.conftest import DbCall
from tests.kb_helpers import (
    COMPANY_URL,
    FakeEmbeddings,
    FakeFetcher,
    count_chunks,
    failure,
    import_kemira,
    kemira_pages,
    make_page,
)

NEW_TEXT = "We now employ 5,100 people across more than sixty countries."


def build(db: DbCall, fetcher: FakeFetcher, embeddings: FakeEmbeddings | None = None) -> Any:
    async def go(session: Any) -> OnboardResult:
        return await onboard(
            session, "kemira", fetcher=fetcher, embeddings=embeddings or FakeEmbeddings()
        )

    return db(go)


def prepared(db: DbCall) -> FakeFetcher:
    db(import_kemira)
    return FakeFetcher(kemira_pages())


async def company_state(session: Any) -> tuple[str, str | None]:
    company = await session.get(Company, "kemira")
    return company.onboarding_status, company.onboarding_error


def test_chunks_are_about_1600_characters_and_overlap() -> None:
    lines = [f"Line {i}: " + "word " * 30 for i in range(60)]
    chunks = chunk_text("\n".join(lines))
    assert len(chunks) > 3
    assert all(len(c) <= CHUNK_SIZE for c in chunks)
    assert any(len(c) > CHUNK_SIZE * 0.6 for c in chunks)
    assert chunks[0].splitlines()[-1] in chunks[1]  # overlap repeats the end of the previous chunk


def test_short_text_is_one_chunk_and_empty_is_none() -> None:
    assert chunk_text("Hello there") == ["Hello there"]
    assert chunk_text("  \n ") == []


def test_onboard_builds_the_collection_and_marks_ready(db: DbCall) -> None:
    fetcher = prepared(db)
    result = build(db, fetcher)
    assert result.status == "ready"
    assert result.indexed == 9
    assert result.chunks_added == db(count_chunks)

    async def state(session: Any) -> Any:
        rows = (await session.scalars(select(KnowledgeSource))).all()
        return await company_state(session), {(r.status, r.last_built_at is not None) for r in rows}

    assert db(state) == (("ready", None), {("ok", True)})


def test_chunks_carry_the_metadata(db: DbCall) -> None:
    build(db, prepared(db))

    async def meta(session: Any) -> dict[str, Any]:
        query = text(
            "SELECT cmetadata, document FROM langchain_pg_embedding WHERE cmetadata->>'url' = :u"
        )
        return dict((await session.execute(query, {"u": COMPANY_URL})).one()._mapping)

    row = db(meta)
    assert row["cmetadata"]["title"] == "About us - Kemira"
    assert row["cmetadata"]["published_date"] == "2025-05-01"
    assert row["cmetadata"]["date_kind"] == "published"
    assert row["cmetadata"]["chunk_index"] == 0
    assert "4,900" in row["document"]
    assert not row["document"].startswith("About us - Kemira")  # stored text is the plain chunk


def test_running_twice_adds_nothing(db: DbCall) -> None:
    fetcher = prepared(db)
    build(db, fetcher)
    before = db(count_chunks)
    embeddings = FakeEmbeddings()
    second = build(db, fetcher, embeddings)
    assert (second.indexed, second.unchanged, second.chunks_added) == (0, 9, 0)
    assert embeddings.calls == 0  # nothing was embedded again
    assert db(count_chunks) == before


def test_changed_page_gets_its_chunks_replaced(db: DbCall) -> None:
    fetcher = prepared(db)
    build(db, fetcher)
    fetcher.pages[COMPANY_URL] = make_page(COMPANY_URL, NEW_TEXT)
    result = build(db, fetcher)
    assert (result.indexed, result.unchanged) == (1, 8)

    async def docs(session: Any) -> list[str]:
        query = text("SELECT document FROM langchain_pg_embedding WHERE cmetadata->>'url' = :u")
        return [r[0] for r in await session.execute(query, {"u": COMPANY_URL})]

    assert db(docs) == [NEW_TEXT]


def test_shorter_page_removes_its_stale_chunks(db: DbCall) -> None:
    fetcher = prepared(db)
    fetcher.pages[COMPANY_URL] = make_page(
        COMPANY_URL, "\n".join(f"Row {i} " + "x " * 400 for i in range(10))
    )
    build(db, fetcher)
    many = db(lambda s: count_chunks(s, COMPANY_URL))
    assert many > 2
    fetcher.pages[COMPANY_URL] = make_page(
        COMPANY_URL, "Just one short paragraph now, with enough words to be kept."
    )
    build(db, fetcher)
    assert db(lambda s: count_chunks(s, COMPANY_URL)) == 1


def test_gone_page_loses_its_chunks_but_temporary_errors_keep_them(db: DbCall) -> None:
    fetcher = prepared(db)
    build(db, fetcher)
    gone, flaky = (str(u) for u in list(fetcher.pages)[1:3])
    fetcher.pages[gone] = failure(gone, "http_error", 410)
    fetcher.pages[flaky] = failure(flaky, "http_error", 503)
    result = build(db, fetcher)
    assert db(lambda s: count_chunks(s, gone)) == 0
    assert db(lambda s: count_chunks(s, flaky)) > 0
    assert (result.sources[gone], result.sources[flaky]) == ("gone", "error")
    assert result.status == "ready"


def test_page_that_left_the_list_is_removed(db: DbCall) -> None:
    fetcher = prepared(db)
    build(db, fetcher)
    leaving = str(list(fetcher.pages)[3])

    async def deactivate(session: Any) -> None:
        await session.execute(
            update(KnowledgeSource).where(KnowledgeSource.url == leaving).values(active=False)
        )
        await session.commit()

    db(deactivate)
    result = build(db, fetcher)
    assert db(lambda s: count_chunks(s, leaving)) == 0
    assert result.removed == 1


def test_all_sources_failing_marks_the_company_failed(db: DbCall) -> None:
    db(import_kemira)
    result = build(db, FakeFetcher({}))
    assert result.status == "failed"
    status, error = db(company_state)
    assert status == "failed"
    assert "no knowledge source" in error


def test_daily_stop_fails_the_run_and_a_second_run_finishes_it(db: DbCall) -> None:
    fetcher = prepared(db)
    embeddings = FakeEmbeddings()
    embeddings.fail_after = 3
    stopped = build(db, fetcher, embeddings)
    assert stopped.status == "failed"
    assert "daily limit" in db(company_state)[1]
    partial = db(count_chunks)
    assert 0 < partial

    finished = build(db, fetcher)
    assert finished.status == "ready"
    assert finished.unchanged == 3
    assert finished.indexed == 6
    assert db(count_chunks) > partial
    assert db(company_state) == ("ready", None)


def test_chunk_ids_are_stable_per_url_and_index() -> None:
    assert chunk_id("kemira", COMPANY_URL, 0) == chunk_id("kemira", COMPANY_URL, 0)
    assert chunk_id("kemira", COMPANY_URL, 0) != chunk_id("kemira", COMPANY_URL, 1)
    assert chunk_id("kemira", COMPANY_URL, 0) != chunk_id("other", COMPANY_URL, 0)
