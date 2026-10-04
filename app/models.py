from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DebugRequest(BaseModel):
    code: str = Field(max_length=50_000)
    stdin: str = Field(default="", max_length=100_000)
    language: Literal["python", "cpp"] = "python"
    # View ids beyond the ones computed up front (`algorithm.views` entries marked `pending`).
    views: list[str] = Field(default_factory=list, max_length=64)


class DebugResponse(BaseModel):
    source: str
    stdin: str
    language: Literal["python", "cpp"] = "python"
    steps: list[dict[str, Any]]
    status: Literal["completed", "exception", "step_limit", "timeout"]
    error: dict[str, str] | None = None
    algorithm: dict[str, Any]
