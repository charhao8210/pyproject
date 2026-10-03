from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DebugRequest(BaseModel):
    code: str = Field(max_length=50_000)
    stdin: str = Field(default="", max_length=100_000)
    language: Literal["python", "cpp"] = "python"


class DebugResponse(BaseModel):
    source: str
    stdin: str
    language: Literal["python", "cpp"] = "python"
    steps: list[dict[str, Any]]
    status: Literal["completed", "exception", "step_limit", "timeout"]
    error: dict[str, str] | None = None
    algorithm: dict[str, Any]
