"""Shared helpers for reading traced values: decoding, shape tests, and lookups."""
from __future__ import annotations

from typing import Any, Iterable

from .serializer import MAX_ITEMS


MAX_VISUAL_ITEMS = 60
MAX_CAPTURE_ITEMS = 500


def decode_scope(step: dict[str, Any], decoded: dict[int, Any] | None = None) -> dict[str, Any]:
    """Decode one step's variables.

    `decoded` caches results by object: the C++ tracer hands every step the same
    value object while a global is unchanged, so a large table is decoded once.
    """
    cache = decoded if decoded is not None else {}
    serialized = {**step.get("globals", {}), **step.get("locals", {})}
    registry: dict[int, dict[str, Any]] = {}
    for value in serialized.values():
        if id(value) not in cache:
            _index_serialized(value, registry)
    scope = {}
    for name, value in serialized.items():
        if id(value) not in cache:
            cache[id(value)] = _decode_value(value, registry, set())
        scope[name] = cache[id(value)]
    return scope


def _index_serialized(value: Any, registry: dict[int, dict[str, Any]]) -> None:
    if not isinstance(value, dict):
        return
    object_id = value.get("object_id")
    if object_id is not None and value.get("type") != "reference":
        registry[object_id] = value
    for item in value.get("items", []):
        _index_serialized(item, registry)
    for entry in value.get("entries", []):
        _index_serialized(entry.get("key"), registry)
        _index_serialized(entry.get("value"), registry)


SET_CLASSES = frozenset({"set", "multiset", "unordered_set"})


class SetItems(list):
    """Decoded members of a set: a list for every view, but never a table of rows."""

    # `usage._changed_cells` marks new members, not positions, of an unordered container.
    unordered = True


class _ObjectFields(dict):
    """Decoded fields of an instance of a class the program defined."""


class PartialItems(list):
    """The first entries of a list too long to read whole; `total` is its real size, if known."""

    def __init__(self, items: Iterable[Any], total: int | None) -> None:
        super().__init__(items)
        self.total = total if isinstance(total, int) and total > len(self) else None


def _decode_value(
    value: Any,
    registry: dict[int, dict[str, Any]],
    seen: set[int],
) -> Any:
    if not isinstance(value, dict):
        return None
    type_name = value.get("type")
    if type_name == "reference":
        target = registry.get(value.get("object_id"))
        return _decode_value(target, registry, seen) if target else None
    if type_name in {"none", "bool", "int", "float", "str"}:
        return value.get("value")
    if type_name == "range":
        range_value = value.get("value", {})
        return list(
            range(
                range_value.get("start", 0),
                range_value.get("stop", 0),
                range_value.get("step", 1),
            )
        )[:MAX_VISUAL_ITEMS]

    object_id = value.get("object_id")
    if object_id is not None:
        if object_id in seen:
            return None
        seen = {*seen, object_id}

    if type_name in {"list", "tuple", "set", "frozenset"}:
        items = [
            _decode_value(item, registry, seen)
            for item in value.get("items", [])[:MAX_CAPTURE_ITEMS]
        ]
        unordered = type_name in {"set", "frozenset"} or value.get("class_name") in SET_CLASSES
        if unordered:
            return SetItems(items)
        if value.get("truncated") and not value.get("fill"):
            # Only the first entries were read; the rest are unknown (not zero).
            return PartialItems(items, value.get("length"))
        return items
    if type_name == "dict":
        # A program's own object (`Node`): its fields, never a graph's adjacency dict.
        decoded: dict[Any, Any] = _ObjectFields() if value.get("class_name") not in (None, "dict") else {}
        for entry in value.get("entries", [])[:MAX_CAPTURE_ITEMS]:
            key = _decode_value(entry.get("key"), registry, seen)
            item = _decode_value(entry.get("value"), registry, seen)
            try:
                decoded[key] = item
            except TypeError:
                decoded[str(key)] = item
        return decoded
    return None


def named_values(
    scope: dict[str, Any],
    name: str | None,
    preferred_names: Iterable[str],
) -> Iterable[tuple[str, Any]]:
    """Candidates for a view: the chosen variable only, or every variable by preference."""
    if name is None:
        return preferred_values(scope, preferred_names)
    return [(name, scope[name])] if name in scope else []


def logical_length(scope: dict[str, Any], values: list[Any], extent: int = 0) -> int:
    """How much of an array to draw.

    Fixed-size C++ arrays (`dp[1000005]`, read up to the item limit) are cut to the part
    used anywhere in the trace (`extent`), so the view keeps one size, and at least to `n`.
    Entries past `n` that hold data stay visible (`dp[n]`, 1-indexed `p[n]`).
    """
    count = scope.get("n")
    has_count = is_index(count) and 0 < count <= len(values)
    capped = len(values) >= MAX_ITEMS and extent > 0
    if not has_count and not capped:
        return len(values)
    floor = max(count if has_count else 0, extent if capped else 0)
    used = len(values)
    while used > floor and not values[used - 1]:
        used -= 1
    return used


def display_value(value: Any, language: str, depth: int = 0) -> str:
    if value is None:
        return "None" if language == "python" else "?"
    if isinstance(value, bool):
        if language == "python":
            return "True" if value else "False"
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, str):
        if language == "python":
            return repr(value)
        return f"'{value}'" if len(value) == 1 else f'"{value}"'
    if isinstance(value, list):
        if depth:
            return "[…]"
        shown = ", ".join(display_value(item, language, depth + 1) for item in value[:4])
        return f"[{shown}{', …' if len(value) > 4 else ''}]"
    if isinstance(value, dict):
        return "{…}"
    return str(value)


def unique_names(names: Iterable[str | None]) -> list[str]:
    """Variable names a visualization draws, so the Variables panel can skip them."""
    return list(dict.fromkeys(name for name in names if name))


def scope_lookup(scope: dict[str, Any], name: str) -> tuple[str, Any]:
    if name in scope:
        return name, scope[name]
    for key, value in scope.items():
        if key.lower() == name:
            return key, value
    return name, None


def is_index(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# Values a distance table starts with for "not reached yet": `-1`, `INF`, `1e9`, `INT_MAX`.
INF_CONSTANTS = frozenset({
    10**9, 10**9 + 7, 10**18, 2**31 - 1, 2**63 - 1, 2**62, 0x3F3F3F3F, 0x3F3F3F3F3F3F3F3F, 10**9 * 2, 10**15, 10**17,
})


def is_infinity(value: Any) -> bool:
    if isinstance(value, float):
        return value == float("inf") or value >= 1e9 and value in {1e9, 1e18, 2e9}
    return is_index(value) and abs(value) in INF_CONSTANTS


def preferred_values(
    scope: dict[str, Any],
    preferred_names: Iterable[str],
) -> Iterable[tuple[str, Any]]:
    yielded: set[str] = set()
    for preferred in preferred_names:
        for name, value in scope.items():
            if name.lower() == preferred:
                yielded.add(name)
                yield name, value
    for name, value in scope.items():
        if name not in yielded:
            yield name, value


def normalize_grid(value: list[Any]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for row in value:
        if isinstance(row, str):
            rows.append(list(row))
        elif isinstance(row, list):
            rows.append(row)
    return rows


def used_rows(value: Any) -> Any:
    """Drop trailing empty rows: a C++ `char a[1005][1005]` only fills its first n rows.

    C++ character rows keep NUL for cells never written (`a[i][0]` of a 1-indexed
    grid) and lose trailing NULs, so those rows are padded back to one width.
    """
    if not isinstance(value, list):
        return value
    end = len(value)
    while end > 0 and value[end - 1] in ("", []):
        end -= 1
    rows = value[:end]
    if rows and all(isinstance(row, str) for row in rows) and any("\0" in row for row in rows):
        width = max(len(row) for row in rows)
        rows = [row.ljust(width, "\0") for row in rows]
    return rows


def is_grid(value: Any) -> bool:
    # A set of pairs (`set<pair<int,int>>`, `{(r, c)}`) has no rows to line up.
    if isinstance(value, SetItems):
        return False
    value = used_rows(value)
    if not isinstance(value, list) or not value:
        return False
    if all(isinstance(row, str) and row for row in value):
        widths = {len(row) for row in value}
        return len(widths) == 1 and min(widths) >= 2
    if all(isinstance(row, list) and row for row in value):
        widths = {len(row) for row in value}
        return len(widths) == 1
    return False


def numeric_array_projection(
    value: Any,
) -> tuple[list[int | float], list[Any] | None] | None:
    if not isinstance(value, list) or not value:
        return None
    if all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value):
        return list(value), None

    numbers: list[int | float] = []
    labels: list[Any] = []
    for item in value:
        # (value, label) pairs; longer rows are a matrix, drawn as a grid instead.
        if isinstance(item, list) and len(item) == 2:
            number, label = item[0], item[1]
        elif isinstance(item, dict) and "first" in item:
            number, label = item["first"], item.get("second")
        else:
            return None
        if not isinstance(number, (int, float)) or isinstance(number, bool):
            return None
        numbers.append(number)
        labels.append(label)
    return numbers, labels


def is_bool_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, bool) for item in value)


def is_flag_array(value: list[Any], numeric_nodes: list[int]) -> bool:
    """Distinguish `visited[node] = True` arrays from lists of visited nodes."""
    if not value:
        return False
    if all(isinstance(item, bool) for item in value):
        return True
    return (
        all(is_index(item) and item in (0, 1) for item in value)
        and bool(numeric_nodes)
        and len(value) > max(numeric_nodes)
    )


def adjacency_rows(
    value: Any,
    vertex_position: int | None = None,
    chosen: list[int] | None = None,
) -> list[tuple[Any, list[tuple[Any, Any]]]] | None:
    """`(source, [(target, weight or None), ...])` per row of an adjacency list or dict.

    Weighted C++ lists hold pairs (`vector<pair<int,int>> adj[N]`); the vertex is the element
    the code treats as one (`vertex_position`, `pair_vertex_position`), else the element that
    is always a valid row index, the first one when both are.
    """
    if isinstance(value, _ObjectFields):
        return None
    if isinstance(value, dict):
        rows = list(value.items())
    elif isinstance(value, list) and len(value) >= 2:
        rows = list(enumerate(value))
    else:
        return None
    if not rows or not all(isinstance(targets, list) for _, targets in rows):
        return None
    flattened = [target for _, targets in rows for target in targets]
    pairs = bool(flattened) and all(
        isinstance(target, list) and len(target) == 2 and all(is_number(item) for item in target)
        for target in flattened
    )
    if pairs:
        limit = len(rows) if isinstance(value, list) else None
        order = (vertex_position, 1 - vertex_position) if vertex_position in (0, 1) else (0, 1)
        for position in order:
            if all(
                is_index(target[position]) and target[position] >= 0
                and (limit is None or target[position] < limit)
                for target in flattened
            ):
                if chosen is not None:
                    chosen.append(position)
                return [
                    (source, [(target[position], target[1 - position]) for target in targets])
                    for source, targets in rows
                ]
        return None
    if isinstance(value, list) and not all(is_index(target) and target >= 0 for target in flattened):
        return None
    return [(source, [(target, None) for target in targets]) for source, targets in rows]


# Names that announce an adjacency list even when every vertex has the same degree.
ADJACENCY_NAMES = frozenset({"graph", "g", "adj", "adjacency", "edges", "children", "child", "tree", "nbr", "nxt"})


def is_adjacency(value: Any, name: str | None = None) -> bool:
    rows = adjacency_rows(value)
    if rows is None:
        return False
    if isinstance(value, dict):
        return True
    targets = [target for _, row in rows for target, _ in row]
    if not targets:
        return False
    if len({len(row) for _, row in rows}) > 1:
        return True
    # Rows of equal length are a numeric table (`ways[h][w]`, `cellEdge[r][c]`) unless the
    # name says graph and every value is a row index.
    return (name is None or name.lower() in ADJACENCY_NAMES) and max(targets) < len(value)
