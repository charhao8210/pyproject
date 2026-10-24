"""The array views: bars for numbers and cells for any values, with index markers."""
from __future__ import annotations

from typing import Any, Iterable

from .classify import AlgorithmProfile
from .values import (
    MAX_CAPTURE_ITEMS,
    MAX_VISUAL_ITEMS,
    PartialItems,
    SetItems,
    display_value,
    is_bool_list,
    is_index,
    is_number,
    logical_length,
    named_values,
    numeric_array_projection,
    scope_lookup,
    unique_names,
)


LOWER_BOUND_NAMES = ("lo", "low", "left", "l")
UPPER_BOUND_NAMES = ("hi", "high", "right", "r")
TARGET_NAMES = ("target", "x", "k", "goal", "key")
SUM_NAMES = ("sum", "s", "cur", "total", "need")
ARRAY_NAMES = ("arr", "a", "nums", "values", "inf", "data")


def array_visualization(
    scope: dict[str, Any],
    profile: AlgorithmProfile,
    name: str | None = None,
    extents: dict[str, tuple[int, int]] | None = None,
) -> dict[str, Any]:
    preferred = ("dp", *profile.focus, *ARRAY_NAMES) if profile.kind == "dynamic_programming" else (*profile.focus, *ARRAY_NAMES)
    candidates = named_values(scope, name, preferred)
    if name is None and profile.focus:
        # Before the written array exists (input being read), draw nothing rather than the input.
        focus = {*profile.focus, *(("dp",) if profile.kind == "dynamic_programming" else ())}
        candidates = [(array_name, value) for array_name, value in candidates if array_name in focus]
    for array_name, value in candidates:
        if isinstance(value, list) and not value and not isinstance(value, SetItems):
            # In scope and empty (`q` after its last pop): drawn empty, never as the last
            # non-empty state, which is only for a variable that left scope.
            return _empty_sequence("array", array_name)
        projection = numeric_array_projection(value)
        if projection is None and array_name in profile.focus and is_bool_list(value):
            # `can[s] = True`: a reachability table, drawn as 0/1 bars.
            projection = [int(item) for item in value], None
        if projection is None:
            continue
        numeric_values, item_labels = projection
        partial = isinstance(value, PartialItems)
        # A partly read list is not cut at its last nonzero entry: what follows is unknown.
        length = len(numeric_values) if partial else logical_length(scope, numeric_values, (extents or {}).get(array_name, (0, 0))[0])
        values = numeric_values[:length][:MAX_VISUAL_ITEMS]
        visualization: dict[str, Any] = {
            "renderer": "array",
            "ready": True,
            "name": array_name,
            "values": values,
            "captured_values": numeric_values[:length][:MAX_CAPTURE_ITEMS],
            "captured_length": min(length, MAX_CAPTURE_ITEMS),
            **({"labels": item_labels[: len(values)]} if item_labels is not None else {}),
            **({"captured_labels": item_labels[:length][:MAX_CAPTURE_ITEMS]} if item_labels is not None else {}),
            "truncated": partial or length > len(values),
        }
        _mark_partial(visualization, value)
        _annotate_indexes(visualization, scope, profile, array_name)
        return visualization
    return {"renderer": "array", "ready": False}


def _empty_sequence(renderer: str, name: str) -> dict[str, Any]:
    return {"renderer": renderer, "ready": True, "name": name, "values": [], "captured_values": [], "captured_length": 0, "truncated": False, "markers": [], "uses": [name]}


def _mark_partial(visualization: dict[str, Any], value: Any) -> None:
    """Record the real size of a list only partly read (`a` has 80 entries, 50 were read)."""
    if isinstance(value, PartialItems) and value.total is not None:
        visualization["length"] = value.total


def cells_visualization(
    scope: dict[str, Any],
    profile: AlgorithmProfile,
    name: str,
    language: str,
    extents: dict[str, tuple[int, int]] | None = None,
) -> dict[str, Any]:
    """A row of cells (Array1D): like the bar view, but for values of any type."""
    value = scope.get(name)
    if isinstance(value, str) and value:
        items = list(value[:MAX_VISUAL_ITEMS])
        length = len(value)
    elif isinstance(value, list) and not value:
        return _empty_sequence("cells", name)
    elif isinstance(value, list):
        partial = isinstance(value, PartialItems)
        length = len(value) if partial else logical_length(scope, value, (extents or {}).get(name, (0, 0))[0])
        items = value[:length][:MAX_VISUAL_ITEMS]
    else:
        return {"renderer": "cells", "ready": False}
    visualization: dict[str, Any] = {
        "renderer": "cells",
        "ready": True,
        "name": name,
        "values": [display_value(item, language) for item in items],
        "captured_values": [display_value(item, language) for item in value[:length][:MAX_CAPTURE_ITEMS]],
        "captured_length": min(length, MAX_CAPTURE_ITEMS),
        "truncated": isinstance(value, PartialItems) or length > len(items),
    }
    _mark_partial(visualization, value)
    _annotate_indexes(visualization, scope, profile, name)
    return visualization


def _annotate_indexes(
    visualization: dict[str, Any],
    scope: dict[str, Any],
    profile: AlgorithmProfile,
    name: str,
) -> None:
    """Add index markers (the entries being read), search bounds, readouts, and `uses`."""
    length = len(visualization["values"])
    searching = profile.kind in {"three_sum", "two_pointers", "binary_search"}
    roles = [
        ("mid", "mid"),
        ("i", "active"),
        ("j", "compare"),
        *((bound, "bound") for bound in LOWER_BOUND_NAMES + UPPER_BOUND_NAMES),
        ("idx", "bound"),
        # In searches `k` is usually the target value rather than an index.
        *(() if searching else (("k", "compare"),)),
    ]
    markers = []
    # Indexes into the part of a long list that was not read: named, so the view can say so.
    beyond = []
    indexes = {variable for _, variable in profile.subscripts}
    for variable, role in roles:
        label, index = scope_lookup(scope, variable)
        # A variable the code uses as an index of other containers only marks those.
        if label in indexes and (name, label) not in profile.subscripts:
            continue
        if is_index(index) and 0 <= index < length:
            markers.append({"index": index, "role": role, "label": label})
        elif is_index(index) and length <= index < visualization.get("length", visualization.get("captured_length", length)):
            beyond.append({"index": index, "label": label})
    visualization["markers"] = markers
    if beyond:
        visualization["beyond"] = beyond

    uses = [name, *(marker["label"] for marker in markers), *(entry["label"] for entry in beyond)]
    if searching:
        interval, bound_names = _search_interval(scope, length)
        if interval is not None:
            visualization["interval"] = interval
            uses.extend(bound_names)
        readouts = []
        for candidates in (SUM_NAMES, TARGET_NAMES):
            for candidate in candidates:
                label, reading = scope_lookup(scope, candidate)
                if is_number(reading):
                    readouts.append({"label": label, "value": reading})
                    break
        if readouts:
            visualization["readouts"] = readouts
            uses.extend(readout["label"] for readout in readouts)
    visualization["uses"] = unique_names(uses)


def _search_interval(
    scope: dict[str, Any],
    length: int,
) -> tuple[dict[str, int] | None, list[str]]:
    """Return the inclusive index window between the search bounds, plus the bound names."""
    lower_name, lower = _first_index(scope, LOWER_BOUND_NAMES)
    upper_name, upper = _first_index(scope, UPPER_BOUND_NAMES)
    if lower is None or upper is None or not length:
        return None, []
    # Bounds outside [-1, length] belong to a search over values, not indexes.
    if not (-1 <= lower <= length and -1 <= upper <= length):
        return None, []
    return {"low": max(0, lower), "high": min(length - 1, upper)}, [lower_name, upper_name]


def _first_index(scope: dict[str, Any], names: Iterable[str]) -> tuple[str | None, int | None]:
    for name in names:
        label, value = scope_lookup(scope, name)
        if is_index(value):
            return label, value
    return None, None
