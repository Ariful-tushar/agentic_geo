"""Company profile schema (SPEC section 5) with all validation rules."""

import re
from decimal import Decimal
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

SLUG_RE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")


class _Strict(BaseModel):
    # Unknown keys are almost always typos in the YAML, so they are errors.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CompetitorIn(_Strict):
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)


class FactQuestionIn(_Strict):
    code: str = Field(min_length=1)
    text: str = Field(min_length=1)
    expected_answer: str = Field(min_length=1)
    expected_value: Decimal | None = None
    tolerance: Decimal | None = Field(default=None, ge=0)
    unit: str | None = None
    expected_source_url: HttpUrl | None = None

    @model_validator(mode="after")
    def numbers_need_expected_value(self) -> Self:
        if self.expected_value is None and (self.tolerance is not None or self.unit is not None):
            raise ValueError(
                f"{self.code}: tolerance and unit are only allowed together with expected_value"
            )
        return self


class GenericQuestionIn(_Strict):
    code: str = Field(min_length=1)
    text: str = Field(min_length=1)


class ProfileIn(_Strict):
    id: str
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    wikipedia_title: str | None = None
    contact_emails: list[EmailStr] = Field(default_factory=list)
    monitoring_enabled: bool = True
    emails_enabled: bool = True
    faq_source_urls: list[HttpUrl] = Field(default_factory=list)
    competitors: list[CompetitorIn] = Field(min_length=1)
    knowledge_sources: list[HttpUrl] = Field(default_factory=list)
    fact_questions: list[FactQuestionIn] = Field(min_length=1)
    generic_questions: list[GenericQuestionIn] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def id_is_slug(cls, value: str) -> str:
        if not SLUG_RE.match(value):
            raise ValueError("id must be a lowercase slug such as 'kemira' or 'acme-corp'")
        return value

    @model_validator(mode="after")
    def no_duplicates(self) -> Self:
        _reject_duplicates(
            "question code",
            [q.code for q in self.fact_questions] + [q.code for q in self.generic_questions],
        )
        _reject_duplicates("competitor name", [c.name.lower() for c in self.competitors])
        _reject_duplicates("knowledge source", [str(u) for u in self.knowledge_sources])
        return self


def _reject_duplicates(label: str, values: list[str]) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label}: {value}")
        seen.add(value)
