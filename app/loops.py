"""Loops in the source, and for each step where to jump to skip its innermost loop."""

from __future__ import annotations

import ast
import re
from typing import Any, NamedTuple

from .cpp_source import _matching_close, _next_top_level_separator, _skip_spaces, _TextIndex, strip_code


class Loop(NamedTuple):
    first_line: int
    last_line: int
    # GDB stops on a C++ `for`/`while` header only when the loop is entered, not on
    # every iteration, so a stop there begins a new run of the loop. Python reports
    # the header on every iteration.
    header_starts_run: bool


def loop_ranges(source: str, language: str) -> list[Loop]:
    """Every loop, from its header line to its last line."""
    if language == "cpp":
        return _cpp_loop_ranges(source)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    return [
        Loop(node.lineno, node.end_lineno or node.lineno, False)
        for node in ast.walk(tree)
        if isinstance(node, (ast.For, ast.While, ast.AsyncFor))
    ]


def _cpp_loop_ranges(source: str) -> list[Loop]:
    text = strip_code(source)
    index = _TextIndex(text)
    ranges: list[Loop] = []
    for match in re.finditer(r"\b(for|while|do)\b", text):
        keyword = match.group(1)
        position = _skip_spaces(text, match.end())
        if keyword == "do":
            body_end = _statement_end(text, index, position)
            if body_end is None:
                continue
            # `do { ... } while (condition);` ends at the semicolon after the condition.
            after = re.match(r"\s*while\s*\(", text[body_end + 1 :])
            if after:
                closing = _matching_close(text, body_end + after.end())
                end = text.find(";", closing) if closing is not None else -1
                if end >= 0:
                    ranges.append(Loop(index.line_of(match.start()), index.line_of(end), False))
            continue
        if position >= len(text) or text[position] != "(":
            continue
        closing = _matching_close(text, position)
        if closing is None:
            continue
        # The `while` closing a do-while has no body of its own.
        if keyword == "while" and re.match(r"\s*;", text[closing + 1 :]) and re.search(r"}\s*$", text[: match.start()]):
            continue
        end = _statement_end(text, index, _skip_spaces(text, closing + 1))
        if end is not None:
            ranges.append(Loop(index.line_of(match.start()), index.line_of(end), True))
    return ranges


def _statement_end(text: str, index: _TextIndex, position: int) -> int | None:
    """Offset of the last character of the statement starting at `position`."""
    if position >= len(text):
        return None
    if text[position] == "{":
        return index.closing_brace(position)
    if text[position] == ";":
        return position
    separator = _next_top_level_separator(text, position)
    while separator is not None and text[separator] == ",":
        separator = _next_top_level_separator(text, separator + 1)
    return separator


def loop_jumps(steps: list[dict[str, Any]], ranges: list[Loop]) -> list[dict[str, Any] | None]:
    """For each step inside a loop: the step just before this run of its innermost loop
    began, and the first step after the run finished.

    A run covers the same call (same depth) on lines within the loop plus any deeper
    calls made from it; returning from the function also ends it.
    """
    depths = [_depth(step) for step in steps]
    loops = [_loop_for(step.get("line"), ranges) for step in steps]
    result: list[dict[str, Any] | None] = [None] * len(steps)
    for index, loop in enumerate(loops):
        if loop is None or result[index] is not None:
            continue
        depth = depths[index]

        def within(other: int) -> bool:
            if depths[other] != depth:
                return depths[other] > depth
            line = steps[other].get("line")
            return isinstance(line, int) and loop.first_line <= line <= loop.last_line

        def starts_run(other: int) -> bool:
            return loop.header_starts_run and depths[other] == depth and steps[other].get("line") == loop.first_line

        # A C++ header stop is the step just before the run, not part of it.
        start = index
        while start > 0 and not starts_run(start) and within(start - 1) and not starts_run(start - 1):
            start -= 1
        after = index + 1
        while after < len(steps) and within(after) and not starts_run(after):
            after += 1
        jump = {
            "line": loop.first_line,
            "end_line": loop.last_line,
            "before": start - 1 if start > 0 else None,
            "after": min(after, len(steps) - 1),
        }
        # Every step of this run of the loop shares the same exits.
        for member in range(start, after):
            if loops[member] == loop and depths[member] == depth:
                result[member] = jump
    return result


def _loop_for(line: Any, ranges: list[Loop]) -> Loop | None:
    """The innermost loop around a line.

    A C++ stop on a loop's header comes before that loop runs, so it belongs to the
    enclosing loop: skipping from a nested loop lands on the next run's header, and
    the next skip then leaves the outer loop.
    """
    if not isinstance(line, int):
        return None
    around = sorted(
        (loop for loop in ranges if loop.first_line <= line <= loop.last_line),
        key=lambda loop: (loop.first_line, -loop.last_line),
        reverse=True,
    )
    if len(around) > 1 and around[0].header_starts_run and around[0].first_line == line:
        return next((loop for loop in around[1:] if loop.first_line != line), around[0])
    return around[0] if around else None


def _depth(step: dict[str, Any]) -> int:
    depth = step.get("depth")
    return depth if isinstance(depth, int) else len(step.get("stack") or [])
