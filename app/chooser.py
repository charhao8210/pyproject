"""The algorithm chooser shown before Run (design approved 2026-11-11).

The user says what the program does instead of the analyzer guessing it. Each choice has slots
(the variables it draws); before Run, `slot_candidates` reads the code and lists the variables
that can fill each slot, most likely first, so the page can pre-fill them. Only declarations
and assignments are read here: nothing runs.
"""

from __future__ import annotations

import ast
import re

from .containers import container_kinds
from .cpp_source import _node_types, _TextIndex, analyze_source, classify_type, expand_aliases, strip_code

# Choice id → (label, slots in order). "other" keeps the analyzer's own guess.
CHOICES: dict[str, tuple[str, tuple[str, ...]]] = {
    "array": ("Array simulation", ("array",)),
    "sorting": ("Sorting", ("array",)),
    "stack": ("Stack", ("stack",)),
    "queue": ("Queue", ("queue",)),
    "linked_list": ("Linked List", ("node",)),
    "bfs": ("BFS", ("graph", "queue")),
    "dfs": ("DFS", ("graph", "stack")),
    "shortest_path": ("Shortest path", ("graph", "distance")),
    "recursion": ("Recursion", ()),
    "other": ("Other", ()),
}
SLOTS = ("array", "graph", "queue", "stack", "node", "distance")

# Which shapes of variable fit each slot, and the names put first.
_FITS = {
    "array": ("1d",),
    "graph": ("2d", "rows", "map"),
    "queue": ("queue", "1d"),
    "stack": ("stack", "1d"),
    "node": ("node",),
    "distance": ("1d",),
}
_PREFERRED = {
    "array": ("arr", "a", "nums", "values", "data"),
    "graph": ("graph", "g", "adj", "adjacency", "edges", "tree", "grid", "maze", "board", "mp", "map"),
    "queue": ("q", "queue", "que", "frontier", "dq"),
    "stack": ("st", "stack", "stk", "s"),
    "node": ("head", "root", "first"),
    "distance": ("dist", "dis", "distance", "d", "dp", "depth", "level"),
}


def slot_candidates(source: str, language: str) -> dict[str, list[str]]:
    """Slot → variable names of the code that fit it, most likely first."""
    try:
        shapes = _cpp_shapes(source) if language == "cpp" else _python_shapes(source)
    except (SyntaxError, ValueError):
        shapes = {}
    kinds = container_kinds(source, language)
    result = {}
    for slot in SLOTS:
        fits = _FITS[slot]
        names = [name for name, shape in shapes.items() if shape in fits]

        def rank(name: str, slot: str = slot, fits: tuple[str, ...] = fits) -> tuple[int, int, int]:
            used_as = 0 if kinds.get(name) == slot or shapes[name] == slot else 1
            preferred = _PREFERRED[slot]
            return (used_as, preferred.index(name) if name in preferred else len(preferred), fits.index(shapes[name]))

        result[slot] = sorted(names, key=rank)
    return result


def _python_shapes(source: str) -> dict[str, str]:
    tree = ast.parse(source)
    node_classes = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and any(
            isinstance(target, ast.Attribute) and target.attr == "next"
            for statement in ast.walk(node)
            if isinstance(statement, ast.Assign)
            for target in statement.targets
        )
    }
    assignments = sorted(
        (
            (node.lineno, node.col_offset, target.id, node.value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
            if isinstance(target, ast.Name)
        ),
        key=lambda item: item[:2],
    )
    shapes: dict[str, str] = {}
    for _, _, name, value in assignments:
        shape = _python_shape(value, node_classes)
        if shape and name not in shapes:
            shapes[name] = shape
    return shapes


def _python_shape(value: ast.expr, node_classes: set[str]) -> str | None:
    def is_rows(element: ast.expr) -> bool:
        return isinstance(element, (ast.List, ast.ListComp)) or (
            isinstance(element, ast.BinOp) and isinstance(element.left, ast.List)
        ) or (isinstance(element, ast.Call) and isinstance(element.func, ast.Name) and element.func.id == "list")

    def is_text(element: ast.expr) -> bool:
        return (isinstance(element, ast.Constant) and isinstance(element.value, str)) or (
            isinstance(element, ast.Call) and isinstance(element.func, ast.Name) and element.func.id == "input"
        )

    if isinstance(value, ast.List):
        if value.elts and all(is_rows(element) for element in value.elts):
            return "2d"
        return "rows" if value.elts and all(is_text(element) for element in value.elts) else "1d"
    if isinstance(value, ast.ListComp):
        return "2d" if is_rows(value.elt) else "rows" if is_text(value.elt) else "1d"
    if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Mult) and isinstance(value.left, ast.List):
        return "2d" if any(is_rows(element) for element in value.left.elts) else "1d"
    if isinstance(value, (ast.Dict, ast.DictComp)):
        return "map"
    if isinstance(value, ast.Attribute) and value.attr == "next" and node_classes:
        return "node"
    if isinstance(value, ast.Call):
        function = value.func
        called = function.id if isinstance(function, ast.Name) else function.attr if isinstance(function, ast.Attribute) else ""
        if called in node_classes:
            return "node"
        if called == "deque":
            return "queue"
        if called in {"dict", "defaultdict"}:
            return "map"
        if called in {"list", "sorted", "split"}:
            return "1d"
    return None


_STRING_ROWS = re.compile(r"^(?:std::)?vector\s*<\s*(?:std::)?string\s*>$")


def _cpp_shapes(source: str) -> dict[str, str]:
    model = analyze_source(source)
    text = strip_code(source)
    lines = text.split("\n")
    index = _TextIndex(text)
    # Struct members (`Node *next`) are fields, not variables.
    members = [(index.line_of(start), index.line_of(end)) for start, end in _node_types(text, index)[1]]
    entries = sorted(
        (declared_line, name, type_text)
        for (_, name), declarations in model.declared_types.items()
        for declared_line, type_text in declarations
    )
    shapes: dict[str, str] = {}
    for declared_line, name, type_text in entries:
        if name in shapes or any(first <= declared_line <= last for first, last in members):
            continue
        line = lines[declared_line - 1] if 0 < declared_line <= len(lines) else ""
        match = re.search(rf"(?<![\w.:>]){re.escape(name)}\s*((?:\[[^\]]*\]\s*)+)", line)
        dimensions = match.group(1).count("[") if match else 0
        base = expand_aliases(type_text, model.aliases).strip()
        if _STRING_ROWS.match(base) or (re.fullmatch(r"(?:std::)?string", base) and dimensions == 1):
            shapes[name] = "rows"
            continue
        classified = classify_type(type_text, dimensions, model.aliases, model.node_types)
        kind = classified[0] if classified else None
        if kind == "array" and classified[1] == "text":
            continue  # a C string
        shape = {
            "array": "1d", "vector": "1d", "bits": "1d",
            "matrix": "2d", "nested": "2d", "vector_array": "2d",
            "queue": "queue", "deque": "queue", "stack": "stack", "list": "node",
        }.get(kind or "")
        if shape:
            shapes[name] = shape
    return shapes
