"""Stack and queue views: which containers a program uses as a stack or a queue, and their models.

Approved layout (2026-11-11): a stack stands upright with its top first and shows only the
10 entries nearest the top; a queue lies front-left to back-right and a long one shows its
first 6 and last 2 entries. Pushed entries are `added` (blue), entries the line reads are
`reading` (dashed yellow), popped ones simply disappear.
"""

from __future__ import annotations

import re
from typing import Any

MAX_STACK_SHOWN = 10
QUEUE_HEAD = 6
QUEUE_TAIL = 2

# `queue<pair<int, int>> q`, `std::stack<int> st`, `deque<int> dq`; priority_queue is a heap
# and is not drawn (the user's choice), and `vector<queue<int>>` is not one queue.
_CPP_DECLARATION = re.compile(
    r"(?<![\w:])(?:std::)?(queue|stack|deque)\s*<(?:[^<>;]|<(?:[^<>;]|<[^<>;]*>)*>)*>\s*([A-Za-z_]\w*)"
)
_PY_LIST_CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\.\s*(?:append|pop|popleft)\s*\(")


def container_kinds(source: str, language: str) -> dict[str, str]:
    """Name → "stack" or "queue" for every container the code uses as one, in source order.

    C++ goes by the declared type (a deque is drawn as a queue). A Python list is a queue when
    the code takes from its front (`pop(0)`, `popleft()`), a stack when it pushes with
    `append` and takes with a bare `pop()`; any other list stays an array.
    """
    kinds: dict[str, str] = {}
    if language == "cpp":
        # shortcut: only the first name of a declaration (`queue<int> a, b;` finds `a`); extend
        # if students declare several queues on one line.
        for match in _CPP_DECLARATION.finditer(source):
            kinds.setdefault(match.group(2), "stack" if match.group(1) == "stack" else "queue")
        return kinds
    for name in dict.fromkeys(_PY_LIST_CALL.findall(source)):
        quoted = re.escape(name)
        if re.search(rf"\b{quoted}\s*\.\s*(?:popleft\s*\(\s*\)|pop\s*\(\s*0\s*\))", source):
            kinds[name] = "queue"
        elif re.search(rf"\b{quoted}\s*\.\s*pop\s*\(\s*\)", source) and re.search(rf"\b{quoted}\s*\.\s*append\s*\(", source):
            kinds[name] = "stack"
    return kinds


def entry_text(item: Any, language: str) -> str:
    """One entry as the views print it; a pair reads `(1, 2)` like the graph and grid queues."""
    if isinstance(item, list) and len(item) == 2 and not any(isinstance(part, list) for part in item):
        return f"({entry_text(item[0], language)}, {entry_text(item[1], language)})"
    if isinstance(item, bool):
        return ("True" if item else "False") if language == "python" else ("true" if item else "false")
    if item is None:
        return "None" if language == "python" else "?"
    if isinstance(item, float):
        return f"{item:g}"
    if isinstance(item, str):
        return repr(item) if language == "python" else f"'{item}'" if len(item) == 1 else f'"{item}"'
    if isinstance(item, list):
        return "[…]"
    if isinstance(item, dict):
        return "{…}"
    return str(item)


def shown_indexes(kind: str, count: int) -> list[int]:
    """Which entries are drawn, in drawing order: a stack top first, a queue front first."""
    if kind == "stack":
        return list(range(count - 1, max(count - 1 - MAX_STACK_SHOWN, -1), -1))
    if count > QUEUE_HEAD + QUEUE_TAIL + 1:
        return [*range(QUEUE_HEAD), *range(count - QUEUE_TAIL, count)]
    return list(range(count))


def reading_indexes(name: str, line_text: str, count: int) -> list[int]:
    """Entries the line reads: `q.front()` / `q[0]` the front, `st.top()` / `back()` / `st[-1]`
    the last. A line that also pops is left unmarked: the drawn state is after the pop."""
    if not count:
        return []
    quoted = re.escape(name)
    if re.search(rf"\b{quoted}\s*\.\s*pop", line_text):
        return []
    found = set()
    if re.search(rf"\b{quoted}\s*(?:\.\s*front\s*\(|\[\s*0\s*\])", line_text):
        found.add(0)
    if re.search(rf"\b{quoted}\s*(?:\.\s*(?:top|back)\s*\(|\[\s*-\s*1\s*\])", line_text):
        found.add(count - 1)
    return sorted(found)


def container_model(kind: str, name: str, value: Any, line_text: str, language: str) -> dict[str, Any]:
    if not isinstance(value, list):
        return {"renderer": kind, "ready": False}
    values = [entry_text(item, language) for item in value]
    total = getattr(value, "total", None)
    model: dict[str, Any] = {
        "renderer": kind,
        "ready": True,
        "name": name,
        "size": total if isinstance(total, int) else len(values),
        # Every entry read, for `_mark_writes`; `entries` are the ones drawn.
        "values": values,
        "entries": [{"index": index, "text": values[index]} for index in shown_indexes(kind, len(values))],
        "reading": reading_indexes(name, line_text, len(values)),
        "uses": [name],
    }
    if isinstance(total, int) and total > len(values):
        # shortcut: only the first 50 entries of a long C++ stack/queue are read, so a stack
        # over 50 shows its bottom part; read the tail in cpp_runner if that matters.
        model["truncated"] = True
    return model


def queue_companion(model: dict[str, Any], scope: dict[str, Any], kinds: dict[str, str], line_text: str, language: str) -> dict[str, Any] | None:
    """The queue drawn above Auto's graph or grid (the user's layout for BFS): the one that view
    already names as its frontier, else the first queue in scope."""
    named = (model.get("frontier") or {}).get("name") if model.get("renderer") == "graph" else (model.get("queue") or {}).get("name")
    candidates = [named] if named and kinds.get(named) == "queue" else []
    candidates += [name for name, kind in kinds.items() if kind == "queue"]
    for name in candidates:
        if isinstance(scope.get(name), list):
            return container_model("queue", name, scope[name], line_text, language)
    return None
