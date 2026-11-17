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

    `changed` is what the line that just ran changed; `new` names variables appearing for the
    first time in the trace (locals per function). `next` and `cells` are what the line about
    to run will change, so the step showing that line can draw its effect: `next` holds the
    serialized value a single value will have afterwards and `after` the same for a container,
    so the variables beside the view show the state after the line, like the view; `cells` marks
    the entries of a container it will change (`items`: positions in a list or dict, new
    members of a set; `cells`: `[row, column]` of a table). Both come from the frame's next
    step, after any calls the line makes have returned.

    `scopes` are the decoded values per step, so aliases and nested containers compare by
    content rather than by how the serializer happened to share them.
    """
    lines = source.split("\n")
    noise = _CPP_NOISE if language == "cpp" else _PYTHON_NOISE
    names_by_line: dict[int, set[str]] = {}
    uninitialised = _uninitialised_declarations(source, language)
    # The last scope seen for each live frame, keyed by stack depth and function name.
    frame_scopes: dict[tuple[int, str], dict[str, Any]] = {}
    # ...and the index of the step it came from, which receives the effect of its line.
    frame_steps: dict[tuple[int, str], int] = {}
    # (function, name) of every local and ("", name) of every global seen so far.
    seen: set[tuple[str, str]] = set()
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
        earlier = frame_steps.get(key) if before is not None else None
        if earlier is not None:
            effect = usage[earlier]
            serialized = {**(step.get("globals") or {}), **(step.get("locals") or {})}
            effect_line = steps[earlier].get("line")
            for name in changed:
                new = serialized.get(name)
                single = isinstance(new, dict) and new.get("type") in SINGLE_VALUE_TYPES
                if name not in before and not _creates(
                    language, names_by_line.get(effect_line, set()), name, uninitialised.get(effect_line, frozenset())
                ):
                    # Only came into view (`int n;` has no stop of its own): nothing to preview.
                    continue
                if name not in before:
                    # Declared by that line again (`int mid` in a loop): listed there with the
                    # value it gets; its first appearance is also marked `new` below.
                    effect["appearing"][name] = {
                        "value": new,
                        "global": name not in (step.get("locals") or {}) and str(step.get("function")) != "<module>",
                    }
                elif single and language == "cpp" and name in effect["new"] and name not in effect["appearing"]:
                    # `int n;` then `cin >> n`: n first shows up at the stop on the reading line,
                    # holding uninitialised memory; list it with the value the line gives it.
                    effect["appearing"][name] = {
                        "value": new,
                        "global": name not in (step.get("locals") or {}) and str(step.get("function")) != "<module>",
                    }
                elif single:
                    effect["next"][name] = new
                else:
                    # The whole container after the line, drawn beside the view (Variables).
                    effect["after"][name] = new
        frame_scopes[key] = scope
        frame_steps[key] = index
        current = {
            "line": on_line, "changed": changed, "new": [], "appearing": {}, "next": {}, "after": {},
        }
        usage.append(current)
        # A variable's first appearance in the whole trace (a loop re-declaring it, or a later
        # call of its function, is not new) belongs to the step showing the line that creates
        # it: `appearing` carries the value it is about to get, since the variable does not
        # exist yet there (C++ hides it, its memory is still garbage). Parameters and the
        # program's first variables have no such step and are new where they appear.
        function = str(step.get("function"))
        # Python module variables are locals at the top level and globals inside functions.
        if function == "<module>":
            function = ""
        for names, owner in ((step.get("locals") or {}, function), (step.get("globals") or {}, "")):
            for name, value in names.items():
                if (owner, name) in seen:
                    continue
                seen.add((owner, name))
                created_there = earlier is not None and _creates(
                    language,
                    names_by_line.get(steps[earlier].get("line"), set()),
                    name,
                    uninitialised.get(steps[earlier].get("line"), frozenset()),
                )
                target = usage[earlier] if created_there else current
                target["new"].append(name)
                if target is not current and name not in target["appearing"]:
                    target["appearing"][name] = {"value": value, "global": owner == "" and name not in (step.get("locals") or {})}
    return usage


SINGLE_VALUE_TYPES = frozenset({"int", "float", "bool", "none", "str", "reference"})


def _creates(language: str, names_on_line: set[str], name: str, uninitialised: frozenset[str] = frozenset()) -> bool:
    """Whether a line can be what creates `name`.

    A C++ variable comes into view at the first stop after its declaration, and a plain
    `int n;` has no stop of its own: the line before it (`cout.tie(0);`) neither creates `n`
    nor gives it its uninitialised value, so that line must not preview it. Neither does
    `int n, T, K, ans = 0;` for n: it only holds garbage until `cin >> n` sets it, so n is
    listed on that line, like a plain `int n;` (`_uninitialised_declarations`).
    """
    return language != "cpp" or (name in names_on_line and name not in uninitialised)


def _uninitialised_declarations(source: str, language: str) -> dict[int, frozenset[str]]:
    """Single C++ values each function line declares without a value (`int n, T, K, ans = 0;`
    → n, T, K)."""
    if language != "cpp":
        return {}
    from .cpp_source import FUNDAMENTAL_TYPES, _normalize_type, analyze_source, expand_aliases, strip_code

    model = analyze_source(source)
    lines = strip_code(source).split("\n")
    result: dict[int, frozenset[str]] = {}
    for line, names in model.line_declarations.items():
        if model.block_for_line(line) is None or not 1 <= line <= len(lines):
            continue
        text = lines[line - 1]
        bare = frozenset(
            name
            for name in names
            if _normalize_type(expand_aliases(model.declared_type(name, line) or "", model.aliases)) in FUNDAMENTAL_TYPES
            and re.search(rf"(?<![\w.]){re.escape(name)}\s*[,;]", text)
            and not re.search(rf"(?<![\w.]){re.escape(name)}\s*[=({{]", text)
        )
        if bare:
            result[line] = bare
    return result


def front_removed(old: list[Any], new: list[Any]) -> int:
    """How many entries left the front of a shrinking list (`q.pop()` of a queue), else 0.

    Every remaining entry moves one position down, so comparing by position would mark all
    of them changed. Removal from the end (`v.pop_back()`) is not counted.
    """
    if len(new) >= len(old) or new == old[: len(new)]:
        return 0
    for shift in range(1, len(old)):
        kept = old[shift:]
        if new[: len(kept)] == kept:
            return shift
    return 0
