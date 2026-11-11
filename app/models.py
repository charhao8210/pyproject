from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Choice(BaseModel):
    """The algorithm picked before Run and the variable for each of its slots (`chooser.CHOICES`)."""

    algorithm: Literal["array", "sorting", "stack", "queue", "linked_list", "bfs", "dfs", "shortest_path", "recursion", "other"]
    variables: dict[str, str] = Field(default_factory=dict, max_length=8)


class CandidatesRequest(BaseModel):
    code: str = Field(max_length=50_000)
    language: Literal["python", "cpp"] = "python"


class DebugRequest(BaseModel):
    code: str = Field(max_length=50_000)
    stdin: str = Field(default="", max_length=100_000)
    language: Literal["python", "cpp"] = "python"
    # View ids beyond the ones computed up front (`algorithm.views` entries marked `pending`).
    views: list[str] = Field(default_factory=list, max_length=64)
    choice: Choice | None = None


class DebugResponse(BaseModel):
    source: str
    stdin: str
    language: Literal["python", "cpp"] = "python"
    steps: list[dict[str, Any]]
    status: Literal["completed", "exception", "step_limit", "timeout"]
    error: dict[str, str] | None = None
    algorithm: dict[str, Any]
    # C++ loop lines that stopped being traced after `loop_stop_limit` stops, with the step
    # of their last stop (`cpp_runner.MAX_LOOP_LINE_STOPS`).
    capped: list[dict[str, int]] = Field(default_factory=list)
    loop_stop_limit: int | None = None
