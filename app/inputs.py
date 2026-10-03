"""Input values: numbers read from stdin that never change afterwards (`n`, `m`, `x`).

The UI shows them once, next to the visualization, instead of in the Variables panel. A value
counts when the last change to its variable was made by a line that reads input and no earlier
change was: `int n; cin >> n;` or `n = 0` then `n = int(input())` qualify, while a value read
inside a loop (once per test case or query, even when it happens to repeat), changed after it
was read, or declared afresh in each loop iteration (it leaves scope and comes back) does not.
Before it is read the variable is hidden (its C++ value is garbage), so every step lists it
with `read: false`.
"""

from __future__ import annotations

import re
from typing import Any

from .loops import loop_ranges

_INPUT_LINE = {
    "cpp": re.compile(r"\b(?:cin|scanf|getline|getchar|fgets|gets)\b"),
    "python": re.compile(r"\binput\s*\(|\bstdin\b"),
}
_NUMBER_TYPES = {"int", "float"}
# Python keeps module-level names in `locals` while the module itself runs.
_MODULE_FRAMES = {"<module>"}


def input_values(source: str, language: str, steps: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Return, for every step, `[{"name", "value", "read"}]` for the input values in scope."""
    lines = source.split("\n")
    pattern = _INPUT_LINE.get(language, _INPUT_LINE["python"])
    reads_input: dict[Any, bool] = {}
    loops = loop_ranges(source, language)

    def in_loop(line: Any) -> bool:
        return isinstance(line, int) and any(loop.first_line <= line <= loop.last_line for loop in loops)

    def is_input_line(line: Any, name: str) -> bool:
        """The line reads stdin into `name` (`cin >> name`, `name = int(input())`)."""
        if line not in reads_input:
            text = lines[line - 1] if isinstance(line, int) and 1 <= line <= len(lines) else ""
            reads_input[line] = text if pattern.search(text) else ""
        text = reads_input[line]
        if not text:
            return False
        # A one-line loop body reads input and computes other values on the same line.
        if language == "cpp":
            return bool(re.search(rf">>\s*{re.escape(name)}\b|&\s*{re.escape(name)}\b", text))
        return bool(re.search(rf"\b{re.escape(name)}\b[^=]*=(?!=)", text))

    # Each key's history of value changes: (step index, whether an input line made it, type).
    last_value: dict[tuple[str, str], Any] = {}
    last_step: dict[tuple[str, str], int] = {}
    changes: dict[tuple[str, str], list[tuple[int, bool, Any]]] = {}
    bindings: list[list[tuple[str, tuple[str, str], dict[str, Any]]]] = []
    # Where each local lives, and the locals that left scope in their own frame and came back.
    frame_of: dict[tuple[str, str], tuple[str, int]] = {}
    absent: set[tuple[str, str]] = set()
    redeclared: set[tuple[str, str]] = set()

    for index, step in enumerate(steps):
        visible = _visible_bindings(step)
        bindings.append(visible)
        frame = (str(step.get("function")), int(step.get("depth", len(step.get("stack") or []))))
        here = {key for _, key, _ in visible}
        for key, home in frame_of.items():
            if home == frame and key not in here:
                absent.add(key)
        for _name, key, value in visible:
            if key[0] != "global":
                frame_of.setdefault(key, frame)
                if key in absent and frame_of[key] == frame:
                    redeclared.add(key)
                    absent.discard(key)
            comparable = (value.get("type"), repr(value.get("value")))
            if key in last_value and last_value[key] == comparable:
                last_step[key] = index
                continue
            if key in last_value and key[0] != "global":
                # A local is changed by the line its own frame last stopped on.
                cause = steps[last_step[key]].get("line")
            else:
                # A global can be changed anywhere; a new name was set by the line just run.
                cause = steps[index - 1].get("line") if index else None
            made_by_input = cause is not None and is_input_line(cause, key[1])
            made_by_input = made_by_input and not in_loop(cause)
            changes.setdefault(key, []).append((index, made_by_input, value.get("type")))
            last_value[key] = comparable
            last_step[key] = index

    read_at: dict[tuple[str, str], int] = {}
    for key, history in changes.items():
        if key in redeclared:
            continue
        *earlier, (index, by_input, kind) = history
        if by_input and kind in _NUMBER_TYPES and not any(made_by_input for _, made_by_input, _ in earlier):
            read_at[key] = index

    result = []
    for index, visible in enumerate(bindings):
        entries = []
        for name, key, value in visible:
            if key not in read_at:
                continue
            read = index >= read_at[key]
            entries.append({"name": name, "value": value.get("value") if read else None, "read": read})
        result.append(entries)
    return result


def _visible_bindings(step: dict[str, Any]) -> list[tuple[str, tuple[str, str], dict[str, Any]]]:
    """(name, key, serialized value) for every variable in scope; locals shadow globals."""
    function = str(step.get("function"))
    frame = "global" if function in _MODULE_FRAMES else function
    locals_ = step.get("locals") or {}
    visible = [(name, (frame, name), value) for name, value in locals_.items() if isinstance(value, dict)]
    visible.extend(
        (name, ("global", name), value)
        for name, value in (step.get("globals") or {}).items()
        if name not in locals_ and isinstance(value, dict)
    )
    return visible
