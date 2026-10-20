import copy
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, Competitor, KnowledgeSource, Question
from app.profiles.loader import import_profile, load_profile_file
from app.schemas.profile import ProfileIn
from tests.conftest import DbCall

KEMIRA = Path(__file__).parents[2] / "seed" / "kemira.profile.yaml"


async def counts(session: AsyncSession) -> dict[str, int]:
    return {
        model.__tablename__: await session.scalar(select(func.count()).select_from(model))
        for model in (Company, Competitor, KnowledgeSource, Question)
    }


def test_importing_twice_creates_no_duplicates(db: DbCall) -> None:
    profile = load_profile_file(KEMIRA)

    first = db(lambda s: import_profile(s, profile))
    after_first = db(counts)
    second = db(lambda s: import_profile(s, profile))

    assert first.company_created and not second.company_created
    assert after_first["questions"] == 24
    assert second.questions_added == second.competitors_added == second.sources_added == 0
    assert db(counts) == after_first


def test_kemira_has_18_fact_and_6_generic_questions(db: DbCall) -> None:
    db(lambda s: import_profile(s, load_profile_file(KEMIRA)))

    async def kinds(s: AsyncSession) -> dict[str, int]:
        rows = await s.execute(select(Question.kind, func.count()).group_by(Question.kind))
        return dict(rows.all())

    assert db(kinds) == {"fact": 18, "generic": 6}


def test_reimport_never_changes_existing_questions(db: DbCall) -> None:
    profile = load_profile_file(KEMIRA)
    db(lambda s: import_profile(s, profile))

    edited = ProfileIn.model_validate({**profile.model_dump(mode="json"), "name": "Renamed"})
    first = edited.fact_questions[0]
    edited.fact_questions[0] = first.model_copy(update={"text": "A different question?"})
    edited.fact_questions.append(first.model_copy(update={"code": "Q99", "text": "New one?"}))
    result = db(lambda s: import_profile(s, edited))

    async def read(s: AsyncSession) -> tuple[str, str, int]:
        company = await s.get(Company, "kemira")
        q01 = await s.scalar(select(Question.text).where(Question.code == "Q01"))
        total = await s.scalar(select(func.count()).select_from(Question))
        return company.name, q01, total

    name, q01_text, total = db(read)
    assert name == "Renamed"  # company fields are updated
    assert q01_text == "Where is Kemira headquartered?"  # existing question untouched
    assert total == 25 and result.questions_added == 1


def test_missing_competitors_and_sources_are_deactivated_then_reactivated(db: DbCall) -> None:
    profile = load_profile_file(KEMIRA)
    db(lambda s: import_profile(s, profile))

    reduced = copy.deepcopy(profile)
    reduced.competitors = [c for c in reduced.competitors if c.name != "Kurita"]
    dropped_url = reduced.knowledge_sources.pop()
    assert db(lambda s: import_profile(s, reduced)).deactivated == 2

    async def state(s: AsyncSession) -> tuple[list[str], list[str], int]:
        off_c = (await s.scalars(select(Competitor.name).where(~Competitor.active))).all()
        off_s = (await s.scalars(select(KnowledgeSource.url).where(~KnowledgeSource.active))).all()
        total = await s.scalar(select(func.count()).select_from(Competitor))
        return list(off_c), list(off_s), total

    assert db(state) == (["Kurita"], [str(dropped_url)], 4)  # nothing deleted

    db(lambda s: import_profile(s, profile))  # they come back in the YAML
    assert db(state) == ([], [], 4)
