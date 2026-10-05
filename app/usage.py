"""Which variables each step uses: names on the line about to run, and values changed since the
last step in the same frame (the effect of the line that just ran)."""

from __future__ import annotations

import ast
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
    frame_scopes: dict[tuple[int, str, int | None], dict[str, Any]] = {}
    # ...and the index of the step it came from, which receives the effect of its line.
    frame_steps: dict[tuple[int, str, int | None], int] = {}
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
        key = (depth, str(step.get("function")), step.get("_frame_id"))
        # A frame deeper than this one has returned; a call event starts a fresh frame.
        for stale in [frame for frame in frame_scopes if frame[0] > depth or key[2] is not None and frame[0] == depth and frame[2] != key[2]]:
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
            effect_text = lines[effect_line - 1] if isinstance(effect_line, int) and 1 <= effect_line <= len(lines) else ""
            for name in changed:
                new = serialized.get(name)
                single = isinstance(new, dict) and new.get("type") in SINGLE_VALUE_TYPES
                if name not in before and not _creates(language, names_by_line.get(effect_line, set()), name):
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
                    marks = _changed_cells(before[name], scope[name])
                    if marks:
                        if "appended" in marks:
                            # Entries the line adds, serialized, drawn after the current ones.
                            items = new.get("items") or [] if isinstance(new, dict) else []
                            marks["appended"] = [items[position] for position in marks["appended"] if position < len(items)]
                        effect["cells"][name] = marks
                if single:
                    formula = assignment_formula(effect_text, name, scopes[earlier], language)
                    if formula:
                        effect["formula"][name] = formula
        frame_scopes[key] = scope
        frame_steps[key] = index
        current = {
            "line": on_line, "changed": changed, "new": [], "appearing": {}, "next": {}, "cells": {}, "formula": {},
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
                    language, names_by_line.get(steps[earlier].get("line"), set()), name
                )
                target = usage[earlier] if created_there else current
                target["new"].append(name)
                if target is not current and name not in target["appearing"]:
                    target["appearing"][name] = {"value": value, "global": owner == "" and name not in (step.get("locals") or {})}
    return usage


# How a line computes a value: `l = ma` → `{"expression": "ma", "substituted": "7"}`, drawn as
# `ma = 7`. Only a line that assigns the name exactly once, with `=`, `op=`, `++` or `--`.
_ASSIGN_OPERATORS = r"(?:\*\*|//|<<|>>|[-+*/%&|^])"
_NOT_VALUES = frozenset({
    "true", "false", "True", "False", "None", "nullptr", "and", "or", "not", "sizeof",
    "int", "long", "double", "float", "char", "bool", "unsigned", "short", "auto", "const",
})


def assignment_formula(line: str, name: str, scope: dict[str, Any], language: str) -> dict[str, str] | None:
    code = re.sub(r"//[^\n]*|/\*.*?\*/", " ", line) if language == "cpp" else line.split("#", 1)[0]
    target = rf"(?<![\w.\]])\b{re.escape(name)}\b"
    assignments = list(re.finditer(rf"{target}\s*({_ASSIGN_OPERATORS})?\s*=(?!=)", code))
    steps = list(re.finditer(rf"{target}\s*(\+\+|--)|(\+\+|--)\s*{re.escape(name)}\b", code))
    if len(assignments) + len(steps) != 1:
        return None
    if steps:
        operator = (steps[0].group(1) or steps[0].group(2))[0]
        expression = f"{name}{operator}1"
    else:
        match = assignments[0]
        right = _right_hand_side(code, match.end())
        if not right:
            return None
        operator = match.group(1)
        expression = f"{name}{operator}{right}" if operator else right
    substituted = _substitute(expression, scope, language)
    return {"expression": expression, "substituted": substituted}


def _right_hand_side(code: str, start: int) -> str:
    """The expression after `=`, up to the `;`, `,` or `)` that ends it."""
    depth = 0
    for position in range(start, len(code)):
        character = code[position]
        if character in "([{":
            depth += 1
        elif character in ")]}":
            if depth == 0:
                return code[start:position].strip()
            depth -= 1
        elif character in ";," and depth == 0:
            return code[start:position].strip()
    return code[start:].strip()


def _substitute(expression: str, scope: dict[str, Any], language: str) -> str:
    """Replace variables (and constant-index entries such as `a[2]`) with their values."""
    def scalar(match: re.Match[str]) -> str:
        name = match.group(0)
        value = scope.get(name, _MISSING)
        if name in _NOT_VALUES or value is _MISSING or not _is_single(value):
            return name
        return _display(value, language)

    text = re.sub(r"(?<![\w.'\"])[A-Za-z_]\w*\b(?!\s*[(\[])", scalar, expression)
    # Entries: `a[0]`, then `g[1][2]`, then `a[b[0]]` once the inner one is a number.
    for _ in range(4):
        replaced = re.sub(r"(?<![\w.])([A-Za-z_]\w*)((?:\[[^\[\]]*\])+)", lambda match: _entry(match, scope, language), text)
        if replaced == text:
            break
        text = replaced
    return text


def _entry(match: re.Match[str], scope: dict[str, Any], language: str) -> str:
    value = scope.get(match.group(1))
    for index_text in re.findall(r"\[([^\[\]]*)\]", match.group(2)):
        index = _integer(index_text)
        if index is None or not isinstance(value, (list, str)) or not -len(value) <= index < len(value):
            return match.group(0)
        value = value[index]
    return _display(value, language) if _is_single(value) else match.group(0)


def _integer(text: str) -> int | None:
    """Evaluate a small integer expression such as `3-1` (a substituted `i-1`)."""
    if not re.fullmatch(r"[\d\s+\-*/%()]+", text) or "**" in text:
        return None
    try:
        tree = ast.parse(text.replace("/", "//"), mode="eval")
    except SyntaxError:
        return None
    if not all(isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.operator, ast.unaryop)) for node in ast.walk(tree)):
        return None
    try:
        result = eval(compile(tree, "<index>", "eval"), {"__builtins__": {}})  # noqa: S307 - digits and operators only
    except ArithmeticError:
        return None
    return result if isinstance(result, int) else None


def _is_single(value: Any) -> bool:
    return isinstance(value, (int, float, str, bool)) or value is None


def _display(value: Any, language: str) -> str:
    if isinstance(value, bool):
        return ("true" if value else "false") if language == "cpp" else str(value)
    if isinstance(value, str):
        return repr(value) if language != "cpp" else f'"{value}"'
    return str(value)


SINGLE_VALUE_TYPES = frozenset({"int", "float", "bool", "none", "str", "reference"})
_MISSING = object()


def _creates(language: str, names_on_line: set[str], name: str) -> bool:
    """Whether a line can be what creates `name`.

    A C++ variable comes into view at the first stop after its declaration, and a plain
    `int n;` has no stop of its own: the line before it (`cout.tie(0);`) neither creates `n`
    nor gives it its uninitialised value, so that line must not preview it.
    """
    return language != "cpp" or name in names_on_line


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


def _changed_cells(old: Any, new: Any) -> dict[str, list[Any]] | None:
    """Positions inside a container whose value differs from the previous step's.

    `appended` holds positions in the new value of entries added at the end (a push), which
    the current value does not have yet.
    """
    items: list[Any] = []
    cells: list[list[int]] = []
    appended: list[int] = []
    if isinstance(new, dict):
        before = old if isinstance(old, dict) else {}
        items = [position for position, (key, value) in enumerate(new.items()) if key not in before or before[key] != value]
    elif isinstance(new, list):
        before_items = old if isinstance(old, list) else []
        removed = front_removed(before_items, new)
        if getattr(new, "unordered", False):
            # Set members have no fixed position: mark the ones that were not there before.
            items = [position for position, value in enumerate(new) if value not in before_items]
        elif removed:
            # The entries about to leave the front; anything after the kept ones is pushed.
            items = list(range(removed))
            appended = list(range(len(before_items) - removed, len(new)))
        else:
            appended = list(range(len(before_items), len(new)))
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
    if not items and not cells and not appended:
        return None
    marks: dict[str, list[Any]] = {"items": items, "cells": cells}
    if appended:
        marks["appended"] = appended
    return marks
