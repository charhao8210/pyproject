"""Which variables each step uses: names on the line about to run, and values changed since the
last step in the same frame (the effect of the line that just ran)."""

from __future__ import annotations

import re
from typing import Any


_IDENTIFIER = re.compile(r"[A-Za-z_]\w*")
_PYTHON_NOISE = re.compile(
    r"#[^\n]*|'''.*?'''|\"\"\".*?\"\"\"|'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\""
)
_CPP_NOISE = re.compile(r"//[^\n]*|/\*.*?\*/|'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"")


def variable_usage(
    source: str,
    language: str,
    steps: list[dict[str, Any]],
    scopes: list[dict[str, Any]],
) -> list[dict[str, list[str]]]:
    """Return `{"line": [...], "changed": [...]}` for every step.

    `scopes` are the decoded values per step, so aliases and nested containers compare by
    content rather than by how the serializer happened to share them.
    """
    lines = source.split("\n")
    noise = _CPP_NOISE if language == "cpp" else _PYTHON_NOISE
    names_by_line: dict[int, set[str]] = {}
    # The last scope seen for each live frame, keyed by stack depth and function name.
    frame_scopes: dict[tuple[int, str], dict[str, Any]] = {}
    usage: list[dict[str, list[str]]] = []

    for step, scope in zip(steps, scopes):
        line = step.get("line")
        if line not in names_by_line:
            text = lines[line - 1] if isinstance(line, int) and 1 <= line <= len(lines) else ""
            names_by_line[line] = set(_IDENTIFIER.findall(noise.sub(" ", text)))
        on_line = [name for name in scope if name in names_by_line[line]]

        depth = int(step.get("depth", len(step.get("stack") or [])))
        key = (depth, str(step.get("function")))
        # A frame deeper than this one has returned; a call event starts a fresh frame.
        for stale in [frame for frame in frame_scopes if frame[0] > depth]:
            del frame_scopes[stale]
        if step.get("event") == "call":
            frame_scopes.pop(key, None)
        before = frame_scopes.get(key)
        changed = (
            [name for name, value in scope.items() if name not in before or before[name] != value]
            if before is not None
            else []
        )
        frame_scopes[key] = scope
        usage.append({"line": on_line, "changed": changed})
    return usage
