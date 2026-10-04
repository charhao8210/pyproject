from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .analyzer import analyze_execution
from .tracer import DEFAULT_MAX_STEPS
from .validator import validate_source


DEFAULT_TIMEOUT_SECONDS = 3.0
# GDB stops at every line (10-15 ms each), so a C++ trace needs far longer than the
# program itself; 3 s would already cut off small CSES sample inputs.
CPP_TIMEOUT_SECONDS = 10.0


class ExecutionTimeoutError(TimeoutError):
    pass


class WorkerExecutionError(RuntimeError):
    pass


def run_debugger(
    source: str,
    *,
    stdin_text: str = "",
    language: str = "python",
    timeout_seconds: float | None = None,
    max_steps: int = DEFAULT_MAX_STEPS,
    extra_views: Iterable[str] = (),
) -> dict[str, Any]:
    if timeout_seconds is None:
        timeout_seconds = CPP_TIMEOUT_SECONDS if language == "cpp" else DEFAULT_TIMEOUT_SECONDS
    if language == "cpp":
        from .cpp_runner import CppExecutionTimeoutError, run_cpp_debugger

        try:
            return run_cpp_debugger(
                source,
                stdin_text=stdin_text,
                timeout_seconds=timeout_seconds,
                max_steps=max_steps,
                extra_views=extra_views,
            )
        except CppExecutionTimeoutError as error:
            raise ExecutionTimeoutError(str(error)) from error
    if language != "python":
        raise ValueError(f"Unsupported language: {language}")

    validate_source(source)
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if max_steps < 1:
        raise ValueError("max_steps must be at least 1")

    project_root = Path(__file__).resolve().parent.parent
    bootstrap = (
        "import runpy,sys;"
        f"sys.path.insert(0,{str(project_root)!r});"
        "runpy.run_module('app.worker',run_name='__main__')"
    )
    command = [sys.executable, "-I", "-S", "-c", bootstrap]
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    with tempfile.TemporaryDirectory(
        prefix="visual-debugger-",
        ignore_cleanup_errors=True,
    ) as workdir:
        trace_path = Path(workdir) / "trace.jsonl"
        payload = json.dumps(
            {
                "code": source,
                "stdin": stdin_text,
                "max_steps": max_steps,
                "trace_file": trace_path.name,
            },
            ensure_ascii=False,
        )
        try:
            completed = subprocess.run(
                command,
                input=payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout_seconds,
                cwd=workdir,
                creationflags=creation_flags,
                check=False,
            )
        except subprocess.TimeoutExpired:
            steps, status, error = _recover_timeout(
                _read_checkpoint_steps(trace_path),
                timeout_seconds,
            )
            result = {
                "source": source,
                "stdin": stdin_text,
                "steps": steps,
                "status": status,
                "error": error,
            }
        else:
            if completed.returncode != 0:
                detail = completed.stderr.strip() or "The debugger subprocess exited unexpectedly."
                raise WorkerExecutionError(detail)

            try:
                result = json.loads(completed.stdout)
            except json.JSONDecodeError as error:
                raise WorkerExecutionError("The debugger subprocess returned invalid JSON.") from error

    result["language"] = "python"
    _mark_exception_origin(result["steps"])
    result["algorithm"] = analyze_execution(source, result["steps"], language="python", extra_views=extra_views)
    return result


def _mark_exception_origin(steps: list[dict[str, Any]]) -> None:
    """Point the final exception step at the line that raised it.

    An uncaught Python exception unwinds frame by frame, so the trace ends on the outermost
    caller (`print(check(x))`); the first exception event of that unwinding is the `raise`.
    """
    if not steps or steps[-1].get("event") != "exception":
        return
    origin = len(steps) - 1
    while origin > 0 and steps[origin - 1].get("event") in {"exception", "return"}:
        origin -= 1
    while steps[origin].get("event") != "exception":
        origin += 1
    first, last = steps[origin], steps[-1]
    if (first.get("line"), first.get("function")) != (last.get("line"), last.get("function")):
        last["exception"] = {**last["exception"], "origin": {"line": first.get("line"), "function": first.get("function")}}


def _recover_timeout(
    steps: list[dict[str, Any]],
    timeout_seconds: float,
) -> tuple[list[dict[str, Any]], str, dict[str, str]]:
    """Close a checkpointed trace with exactly one terminal `stopped` step."""
    error = {
        "type": "TimeoutError",
        "message": f"Execution exceeded the {timeout_seconds:g} second timeout.",
    }
    if steps and steps[-1].get("event") == "stopped":
        # The trace already ended at the step limit; only returning the result
        # missed the deadline, so keep that terminal step instead of adding one.
        return steps, "step_limit", steps[-1].get("exception") or error
    if steps:
        stopped = {key: value for key, value in steps[-1].items() if key != "return_value"}
        stopped["step"] = len(steps)
        stopped["event"] = "stopped"
        stopped["exception"] = error
        return [*steps, stopped], "timeout", error
    return (
        [
            {
                "step": 0,
                "event": "stopped",
                "filename": "<user_code>",
                "function": "<module>",
                "line": 1,
                "locals": {},
                "globals": {},
                "stack": [],
                "stdout": "",
                "exception": error,
            }
        ],
        "timeout",
        error,
    )


def _read_checkpoint_steps(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    steps: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            step = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(step, dict):
            steps.append(step)
    return steps
