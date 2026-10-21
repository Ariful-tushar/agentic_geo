"""Shapes shared by the AI layer and the agents."""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Citation(BaseModel):
    url: str
    title: str | None = None


class EngineAnswer(BaseModel):
    """What a tested engine said, exactly as returned (never cached)."""

    text: str
    citations: list[Citation] = Field(default_factory=list)
    model: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    latency_ms: int = 0
    raw_json: dict[str, Any] = Field(default_factory=dict)


class EngineConfig(BaseModel):
    """One entry of backend/config/engines.yaml."""

    id: str
    provider: str
    model_env: str
    web_search: bool = False
    enabled: bool = True
    label: str


class RagQuote(BaseModel):
    """A quote the AI says supports its answer; `chunk` is a label like "C2"."""

    chunk: str
    text: str


class RagAnswer(BaseModel):
    """What our AI returns for a RAG question (before the quotes are verified)."""

    found: bool
    answer: str = ""
    quotes: list[RagQuote] = Field(default_factory=list)


class VerifiedQuote(BaseModel):
    text: str
    url: str
    title: str | None = None


class RagResult(BaseModel):
    """Final RAG answer. `answer` is NOT_FOUND unless at least one quote was verified."""

    found: bool
    answer: str
    quotes: list[VerifiedQuote] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    # Debug only: the model's unverified draft and the retrieved chunks. Never shown or scored.
    raw_json: dict[str, Any] = Field(default_factory=dict)


Verdict = Literal["correct", "partial", "wrong", "no_answer"]
MAX_REASON_WORDS = 25


class JudgeItem(BaseModel):
    """The judge's opinion on one answer."""

    code: str
    verdict: Verdict
    quote: str = ""
    reason: str = ""

    @field_validator("reason")
    @classmethod
    def _short_reason(cls, value: str) -> str:
        return " ".join(value.split()[:MAX_REASON_WORDS])


class JudgeBatch(BaseModel):
    items: list[JudgeItem]


class WhyAnswer(BaseModel):
    """Our AI's answer to: does this source contain the wrong claim?"""

    found: bool
    source: str = ""  # label of the source that holds the claim, e.g. "S2"
    evidence_quote: str = ""
    explanation: str = ""


class OtherBrandsItem(BaseModel):
    code: str
    names: list[str] = Field(default_factory=list)


class OtherBrands(BaseModel):
    """Company names (other than the tracked ones) the AI sees in each generic answer."""

    items: list[OtherBrandsItem]
