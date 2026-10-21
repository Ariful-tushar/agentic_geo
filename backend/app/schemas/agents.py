"""Shapes shared by the AI layer and the agents."""

from typing import Any

from pydantic import BaseModel, Field


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
    """One entry of config/engines.yaml."""

    id: str
    provider: str
    model_env: str
    web_search: bool = False
    enabled: bool = True
    label: str
