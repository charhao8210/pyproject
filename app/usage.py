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
) -> list[dict[str, Any]]:
    """Return `{"line": [...], "changed": [...], "next": {...}, "cells": {...}}` for every step.

    `changed` is what the line that just ran changed. `next` and `cells` are what the line about
    to run will change, so the step showing that line can draw its effect: `next` holds the
    serialized value a single value will have afterwards (drawn as `old -> new`), `cells` marks
    the entries of a container it will change (`items`: positions in a list or dict, new
    members of a set; `cells`: `[row, column]` of a table). Both come from the frame's next
    step, after any calls the line makes have returned.

    `scopes` are the decoded values per step, so aliases and nested containers compare by
    content rather than by how the serializer happened to share them.
    """
    lines = source.split("\n")
    noise = _CPP_NOISE if language == "cpp" else _PYTHON_NOISE
    names_by_line: dict[int, set[str]] = {}
    # The last scope seen for each live frame, keyed by stack depth and function name.
    frame_scopes: dict[tuple[int, str], dict[str, Any]] = {}
    # ...and the index of the step it came from, which receives the effect of its line.
    frame_steps: dict[tuple[int, str], int] = {}
    usage: list[dict[str, Any]] = []

    for index, (step, scope) in enumerate(zip(steps, scopes)):
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
            frame_steps.pop(stale, None)
        if step.get("event") == "call":
            frame_scopes.pop(key, None)
            frame_steps.pop(key, None)
        before = frame_scopes.get(key)
        changed = (
            [name for name, value in scope.items() if name not in before or before[name] != value]
            if before is not None
            else []
        )
        if before is not None:
            effect = usage[frame_steps[key]]
            serialized = {**(step.get("globals") or {}), **(step.get("locals") or {})}
            for name in changed:
                if name not in before:
                    continue
                new = serialized.get(name)
                if isinstance(new, dict) and new.get("type") in SINGLE_VALUE_TYPES:
                    effect["next"][name] = new
                marks = _changed_cells(before[name], scope[name])
                if marks:
                    effect["cells"][name] = marks
        frame_scopes[key] = scope
        frame_steps[key] = index
        usage.append({"line": on_line, "changed": changed, "next": {}, "cells": {}})
    return usage


SINGLE_VALUE_TYPES = frozenset({"int", "float", "bool", "none", "str", "reference"})
_MISSING = object()


def _changed_cells(old: Any, new: Any) -> dict[str, list[Any]] | None:
    """Positions inside a container whose value differs from the previous step's."""
    items: list[Any] = []
    cells: list[list[int]] = []
    if isinstance(new, dict):
        before = old if isinstance(old, dict) else {}
        items = [position for position, (key, value) in enumerate(new.items()) if key not in before or before[key] != value]
    elif isinstance(new, list):
        before_items = old if isinstance(old, list) else []
        if getattr(new, "unordered", False):
            # Set members have no fixed position: mark the ones that were not there before.
            items = [position for position, value in enumerate(new) if value not in before_items]
        else:
            for index, value in enumerate(new):
                previous = before_items[index] if index < len(before_items) else _MISSING
                if previous == value:
                    continue
                items.append(index)
                # A row of a table (or a character row) also names its changed columns.
                if isinstance(value, (list, str)):
                    row = previous if isinstance(previous, (list, str)) else ()
                    cells.extend(
                        [index, column]
                        for column, item in enumerate(value)
                        if column >= len(row) or row[column] != item
                    )
    if not items and not cells:
        return None
    return {"items": items, "cells": cells}
