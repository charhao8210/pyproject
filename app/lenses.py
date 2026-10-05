"""Small semantic views built from source evidence and recorded program state.

These lenses do not execute expressions or manufacture library-internal events.  A
heap snapshot, for example, is a heap snapshot, not a replay of unrecorded sifts.
The analyzer supplies decoded scopes and the current ``_source_line`` temporarily.
"""

from __future__ import annotations

import ast
import io
import math
import operator
import re
import tokenize
from typing import Any


MAX_ITEMS = 500
MAX_NODES = 60
MAX_READS = 24
RENDERERS = frozenset({"heap", "window", "monotonic", "fenwick", "string_match", "trie"})
_NAME = r"[A-Za-z_]\w*"
_ALIASES = {"sliding_window": "window", "kmp": "string_match", "priority_queue": "heap", "bit": "fenwick"}
_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.BitAnd: operator.and_,
    ast.BitOr: operator.or_, ast.BitXor: operator.xor, ast.LShift: operator.lshift,
    ast.RShift: operator.rshift,
}
_SUBSCRIPT = re.compile(rf"\b({_NAME})\s*\[([^\[\]\n]{{1,80}})\](?:\s*\[([^\[\]\n]{{1,80}})\])?")


def extend_catalog(
    source: str,
    scopes: list[dict[str, Any]],
    steps: list[dict[str, Any]],
    language: str = "python",
    bindings: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Offer extra views only when a source pattern or explicit binding supports it."""
    bindings = bindings or {}
    code = _strip_source(source, language)
    names: list[str] = []
    for scope in scopes:
        for name, value in scope.items():
            if not name.startswith("__") and isinstance(value, (list, str, dict)) and name not in names:
                names.append(name)
    catalog: list[dict[str, Any]] = []
    offered: set[tuple[str, str]] = set()
    mode = _ALIASES.get(bindings.get("mode", ""), bindings.get("mode", ""))
    forced = bindings.get("primary")

    def add(renderer: str, name: str, **spec: Any) -> None:
        if (renderer, name) in offered:
            return
        if renderer not in {"string_match", "trie"} and not any(isinstance(s.get(name), list) for s in scopes):
            return
        offered.add((renderer, name))
        catalog.append({"id": f"{renderer}:{name}", "renderer": renderer, "variable": name, "preferred": True, **spec})

    if forced and mode in RENDERERS:
        add(mode, bindings.get("stack", forced) if mode == "monotonic" else forced, manual=True)

    heap_functions = {"heappush", "heappop", "heapify", "heappushpop", "heapreplace", "heappush_max", "heappop_max", "heapify_max", "heappushpop_max", "heapreplace_max"}
    module_aliases, imported_functions = set(), {}
    if language == "python":
        try:
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Import):
                    module_aliases.update(alias.asname or alias.name for alias in node.names if alias.name == "heapq")
                elif isinstance(node, ast.ImportFrom) and node.module == "heapq":
                    imported_functions.update({alias.asname or alias.name: alias.name for alias in node.names if alias.name in heap_functions})
        except SyntaxError:
            pass
    helper_names = heap_functions | set(imported_functions)
    helpers = "|".join(map(re.escape, sorted(helper_names, key=len, reverse=True)))
    heap_records = list(re.finditer(rf"(?:(?P<module>{_NAME})\s*\.\s*)?\b(?P<helper>{helpers})\s*\(\s*(?P<array>{_NAME})", code))
    heap_calls = {match.group("array") for match in heap_records}
    heap_classes = {
        name for step in steps for name, value in _serialized_scope(step).items()
        if isinstance(value, dict) and value.get("class_name") == "priority_queue"
    }
    heap_declarations = set(re.findall(rf"\bpriority_queue\s*<[^;\n]*>\s*({_NAME})\s*[;(]", code))
    for name in names:
        if name in heap_calls | heap_classes | heap_declarations or (
            name.lower() in {"heap", "pq"} and re.search(r"(?:2\s*\*\s*\w+|\w+\s*\*\s*2)\s*\+\s*1", code)
        ):
            declaration = next((line for line in code.splitlines() if "priority_queue" in line and re.search(rf"\b{re.escape(name)}\b", line)), "")
            python_orders = {
                "max" if imported_functions.get(match.group("helper"), match.group("helper")).endswith("_max") else "min"
                for match in heap_records if match.group("array") == name and (match.group("module") in module_aliases or not match.group("module") and match.group("helper") in imported_functions)
            }
            custom_comparator = re.search(rf",\s*(?:std::)?({_NAME})\s*>\s*{re.escape(name)}\b", declaration)
            order = next(iter(python_orders)) if len(python_orders) == 1 else "min" if "greater" in declaration else "max" if "priority_queue" in declaration and (not custom_comparator or custom_comparator.group(1) == "less") else "unknown"
            add("heap", name, order=order)

    left = _existing_name(scopes, bindings.get("left"), ("left", "l", "lo", "start"), scalar=True)
    right = _existing_name(scopes, bindings.get("right"), ("right", "r", "hi", "end"), scalar=True)
    if left and right and not re.search(r"\bmid\b", code):
        candidates = [name for name in names if any(isinstance(s.get(name), list) for s in scopes)]
        indexed = [name for name in candidates if re.search(rf"\b{re.escape(name)}\s*\[\s*(?:{re.escape(left)}|{re.escape(right)})\b", code)]
        for name in ([forced] if mode == "window" and forced else indexed[:3]):
            exclusive_slice = bool(re.search(rf"\b{re.escape(name)}\s*\[\s*{re.escape(left)}\s*:\s*{re.escape(right)}\s*\]", code))
            add("window", name, left=left, right=right, inclusive=not exclusive_slice)

    for name in names:
        escaped = re.escape(name)
        popping = re.search(rf"\b{escaped}\s*\.\s*(?:pop|pop_back|pop_front|popleft)\s*\(", code)
        pushing = re.search(rf"\b{escaped}\s*\.\s*(?:append|appendleft|push|push_back|push_front)\s*\(", code)
        # Compare the top itself (or an array entry indexed by it); C++ stream/shift
        # operators after `front()` do not make an ordinary queue monotonic.
        top_comparison = re.search(rf"\b{escaped}\s*(?:\[\s*-\s*1\s*\]|\.\s*(?:top|back|front)\s*\(\s*\))\s*[\])]*\s*([<>])(?![<>])", code)
        indexed_comparison = re.search(rf"\[\s*{escaped}\s*\[\s*-\s*1\s*\]\s*\]\s*[\])]*\s*([<>])(?![<>])", code)
        comparison = indexed_comparison or top_comparison
        if popping and pushing and comparison:
            add("monotonic", name, direction="increasing" if comparison.group(1) == ">" else "decreasing", role="deque" if re.search(rf"\b{escaped}\s*\.\s*(?:popleft|pop_front|appendleft|push_front)", code) else "stack")

    lowbit = re.search(rf"\b({_NAME})\s*&\s*-\s*\1\b", code) or re.search(r"\blowbit\s*\(", code)
    if lowbit:
        index = lowbit.group(1) if lowbit.lastindex else "i"
        candidates = [name for name in names if re.search(rf"\b{re.escape(name)}\s*\[\s*{re.escape(index)}\s*\]", code)]
        for name in candidates:
            if name.lower() in {"bit", "fenwick", "tree", "ft", "fen"} or re.search(rf"\b{re.escape(name)}\s*\[\s*{re.escape(index)}\s*\]\s*\+=", code):
                add("fenwick", name, index=index)

    text = _existing_name(scopes, bindings.get("text"), ("text", "haystack", "s"), string=True)
    pattern = _existing_name(scopes, bindings.get("pattern"), ("pattern", "pat", "needle", "p"), string=True)
    if text and pattern and text != pattern and (
        mode == "string_match" or re.search(rf"\b{re.escape(text)}\s*\[", code) and re.search(rf"\b{re.escape(pattern)}\s*\[", code)
    ):
        add("string_match", forced or text, text=text, pattern=pattern)

    for name in names:
        if name.lower() in {"trie", "root", "children", "nxt", "next"} and (
            re.search(r"\b(?:trie|Trie)\b", code) or mode == "trie"
        ) and any(_trie_shape(s.get(name)) for s in scopes):
            add("trie", name)
    return catalog


def view_model(
    view: dict[str, Any],
    scope: dict[str, Any],
    step: dict[str, Any],
    previous_scope: dict[str, Any] | None = None,
    bindings: dict[str, str] | None = None,
) -> dict[str, Any]:
    bindings = bindings or {}
    renderer, name = view["renderer"], view["variable"]
    value = scope.get(name)
    if renderer == "string_match":
        model = _string_model(view, scope, step, bindings)
    elif renderer == "trie":
        model = _trie_model(view, scope, step, bindings)
    elif not isinstance(value, list):
        return {"renderer": renderer, "ready": False, "name": name}
    else:
        model = _base(renderer, name, value, step)
        if renderer == "heap":
            bound_order = bindings.get("heap_order")
            model.update(order=bound_order if bound_order in {"min", "max"} else view.get("order", "unknown"), top=_plain(value[0]) if value else None)
            model["nodes"] = [
                {"id": index, "index": index, "value": _plain(item), "parent": (index - 1) // 2 if index else None,
                 "left": 2 * index + 1 if 2 * index + 1 < len(model["values"]) else None,
                 "right": 2 * index + 2 if 2 * index + 2 < len(model["values"]) else None}
                for index, item in enumerate(model["values"][:MAX_NODES])
            ]
            model["notes"] = ["Storage is heap order; internal sift steps appear only when traced in your code."]
        elif renderer == "window":
            _window_fields(model, view, scope, previous_scope, bindings)
        elif renderer == "monotonic":
            _monotonic_fields(model, view, scope, previous_scope, bindings)
        elif renderer == "fenwick":
            _fenwick_fields(model, view, scope, step, bindings)
    if model.get("ready"):
        enrich_model(model, step, scope, previous_scope, bindings)
    return model


def enrich_model(
    model: dict[str, Any],
    step: dict[str, Any],
    scope: dict[str, Any],
    previous_scope: dict[str, Any] | None = None,
    bindings: dict[str, str] | None = None,
) -> None:
    """Describe actual reads and traced writes without guessing successful outcomes."""
    if not model.get("ready"):
        return
    bindings = bindings or {}
    source = _current_source(step)
    language = _step_language(step)
    usage = step.get("usage") or {}
    after_scope = step.get("_after_scope")
    after_scope = after_scope if isinstance(after_scope, dict) else None
    reads = _read_entries(source, scope, language)
    if isinstance(step.get("usage"), dict):
        read_marks: dict[str, dict[str, list]] = {}
        for entry in reads:
            marks = read_marks.setdefault(entry["name"], {"items": [], "cells": []})
            field = "cells" if "cell" in entry else "items"
            value = entry.get("cell", entry.get("index"))
            if value not in marks[field]:
                marks[field].append(value)
        step["usage"]["reads"] = read_marks
    writes = _write_entries(model, scope, after_scope, usage)
    relevant = set(model.get("uses") or []) | {model.get("name")}
    bound_names = {bindings[key] for key in ("distance", "parent", "lazy", "frontier", "prefix", "indegree", "output") if bindings.get(key)}
    relevant |= bound_names
    dp_model = model.get("renderer") in {"grid", "array", "cells"} and (str(model.get("name", "")).lower() in {"dp", "memo", "ways", "best", "can", "f"} or bindings.get("mode") in {"dp", "dynamic_programming"})
    if dp_model:
        relevant |= {entry["name"] for entry in reads}
    if model.get("renderer") == "graph":
        for field in ("frontier", "labels"):
            if isinstance(model.get(field), dict) and model[field].get("name"):
                relevant.add(model[field]["name"])
    if model.get("renderer") == "segment_tree":
        for candidate in (bindings.get("lazy"), "lazy", "tag", "lz"):
            if candidate in scope:
                relevant.add(candidate)
    if model.get("renderer") == "graph":
        relevant |= {read["name"] for read in reads if read.get("index") is not None}
    reads = [entry for entry in reads if entry["name"] in relevant][:MAX_READS]
    writes = [entry for entry in writes if entry["name"] in relevant][:MAX_READS]
    kind, label = "inspect", "Read state"
    name = model.get("name", "")
    before = scope.get(name)
    after = after_scope.get(name) if after_scope is not None else model.get("values")
    operation_name = bindings.get("frontier") or (model.get("frontier") or {}).get("name", name) if model.get("renderer") == "graph" else name
    if operation_name != name:
        before = scope.get(operation_name)
        after = after_scope.get(operation_name) if after_scope is not None else None
    direct_container = re.search(rf"\b{re.escape(str(operation_name))}\s*\.\s*(append|push|push_back|appendleft|push_front|pop|pop_back|pop_front|popleft)\s*\(", source)
    heap_call = re.search(rf"\b(heappush|heappop)\s*\(\s*{re.escape(str(operation_name))}\b", source)
    method = direct_container.group(1) if direct_container else heap_call.group(1) if heap_call else ""
    if method and isinstance(before, list) and isinstance(after, list) and len(before) != len(after):
        kind = "push" if len(after) > len(before) else "pop"
        label = "Insert item (traced)" if kind == "push" else "Remove item (traced)"
    elif writes:
        kind, label = "update", "Update state (traced)"
    elif reads and any(op in source for op in ("<", ">", "==", "!=")):
        kind, label = "compare", "Compare recorded values"
    renderer = model.get("renderer")
    if renderer == "fenwick":
        model["accesses"] = list(dict.fromkeys(entry["index"] for entry in reads if entry["name"] == name and "index" in entry))
        if re.search(rf"\b{re.escape(str(name))}\s*\[[^\]]+\]\s*(?:\+=|-=|=(?!=))", source):
            kind, label = ("update", "Update Fenwick range (traced)") if writes else ("inspect", "Fenwick update line")
        elif reads:
            kind, label = "query", "Read Fenwick range"
    if renderer == "graph" and writes and any(entry["name"].lower() in {"dist", "distance", "dis", "d"} or entry["name"] == bindings.get("distance") for entry in writes):
        kind, label = "relax", "Distance update (traced)"
    if renderer == "dsu" or model.get("layout") == "forest":
        if writes:
            label = "Parent update (traced)"
    operation = {"kind": kind, "label": label, "source": source, "reads": reads, "writes": writes, "evidence": "trace"}
    formulas = usage.get("formula") or {}
    if formulas:
        operation["formula"] = {name: value for name, value in formulas.items() if name in relevant or name in usage.get("line", [])}
    if renderer == "window" and model.get("pointer_changes"):
        operation["kind"], operation["label"] = "move", "Window boundary changed (traced)"
    if reads or writes or source or formulas:
        model["operation"] = operation
    if renderer == "string_match":
        _string_comparison(model, source, scope, bindings, language)
    if dp_model:
        model["dependencies"] = reads
        model["destinations"] = writes
        indexed_assignment = re.search(rf"(?P<target>\b{re.escape(name)}\s*\[[^\]]+\](?:\s*\[[^\]]+\])?)\s*(?P<operator>(?:\*\*|//|[-+*/%&|^])?=)(?!=)\s*(?P<expression>.+)", _strip_source(source, language)) if any(entry["name"] == name for entry in writes) else None
        if indexed_assignment:
            expression = indexed_assignment.group("expression").split(";", 1)[0].rstrip()
            assign_operator = indexed_assignment.group("operator")
            if assign_operator != "=":
                expression = f"{indexed_assignment.group('target')} {assign_operator[:-1]} ({expression})"
            operation["expression"] = expression
            operation["substituted"] = _SUBSCRIPT.sub(lambda match: _substitute_read(match, scope), operation["expression"])
            candidate = _safe_expression(operation["expression"], scope) if language != "cpp" else _MISSING
            if candidate is not _MISSING and isinstance(candidate, (int, float, bool, str)):
                operation["candidate"] = {"value": _plain(candidate), "expression": operation["expression"]}
    if renderer in {"array", "cells"} and not dp_model:
        _sorting_fields(model, step, scope, bindings)
    if renderer == "grid":
        row = _scope_name(scope, bindings.get("row"), (), scalar=True)
        column = _scope_name(scope, bindings.get("column"), (), scalar=True)
        if row and column:
            model["current_cell"] = [scope[row], scope[column]]
    if renderer == "graph":
        post = after_scope or scope
        distance = bindings.get("distance")
        if distance and isinstance(post.get(distance), list):
            values = post[distance]
            model["labels"] = {"name": distance, "values": {str(node): _plain(values[int(node)]) for node in model.get("nodes", []) if str(node).isdigit() and int(node) < len(values)}}
            model["uses"] = list(dict.fromkeys([*(model.get("uses") or []), distance]))
        frontier = bindings.get("frontier")
        if frontier and isinstance(post.get(frontier), list):
            from .analyzer import _graph_frontier
            values = post[frontier][:MAX_ITEMS]
            _, vertices, entries = _graph_frontier({"frontier": values}, set(map(str, model.get("nodes", []))))
            model["frontier"] = {"name": frontier, "items": vertices, "entries": entries or [str(_plain(value)) for value in values]}
            model["uses"] = list(dict.fromkeys([*(model.get("uses") or []), frontier]))
        index = bindings.get("index")
        if index and str(scope.get(index)) in set(map(str, model.get("nodes", []))):
            model["current"] = str(scope[index])
            model["uses"] = list(dict.fromkeys([*(model.get("uses") or []), index]))
        _graph_teaching(model, source, post, bindings)
    if renderer == "segment_tree":
        lazy = _scope_name(scope, bindings.get("lazy"), ("lazy", "tag", "lz"), sequence=True)
        if lazy:
            model["lazy"] = {"name": lazy, "values": {str(index): _plain(value) for index, value in enumerate(scope[lazy][:MAX_ITEMS])}, "truncated": _partial(scope[lazy], step, lazy)}
            model["uses"] = list(dict.fromkeys([*(model.get("uses") or []), lazy]))
        low = _scope_name(scope, bindings.get("query_left") or bindings.get("left"), ("ql", "query_l", "query_left"), scalar=True)
        high = _scope_name(scope, bindings.get("query_right") or bindings.get("right"), ("qr", "query_r", "query_right"), scalar=True)
        if low and high:
            model["query"] = {"low": scope[low], "high": scope[high], "inclusive": True}


def _sorting_fields(model: dict, step: dict, scope: dict, bindings: dict) -> None:
    model.pop("sorting", None)
    name, source = model.get("name", ""), _strip_source(_current_source(step), _step_language(step))
    pivot_name = _scope_name(scope, bindings.get("pivot"), ("pivot", "pivot_value", "pivot_index", "pivotIndex"), numeric=True)
    function = str(step.get("function", "")).lower()
    evident = bindings.get("mode") == "sorting" or pivot_name is not None or any(word in function for word in ("sort", "partition", "merge"))
    if not evident or not isinstance(scope.get(name), list):
        return
    fields: dict[str, Any] = {}
    values = scope[name]
    if pivot_name:
        pivot = scope[pivot_name]
        indexed = "index" in pivot_name.lower() or re.search(rf"\b{re.escape(name)}\s*\[\s*{re.escape(pivot_name)}\s*\]", source)
        if indexed and _int(pivot) and 0 <= pivot < len(values):
            fields["pivot"] = {"name": pivot_name, "index": pivot, "value": _plain(values[pivot])}
        else:
            fields["pivot"] = {"name": pivot_name, "value": _plain(pivot)}
    left = _scope_name(scope, bindings.get("left"), ("lo", "low", "l", "left", "start"), scalar=True)
    right = _scope_name(scope, bindings.get("right"), ("hi", "high", "r", "right", "end"), scalar=True)
    if left and right:
        exclusive = bindings.get("right_exclusive")
        fields["range"] = {"low": scope[left], "high": scope[right], "left_name": left, "right_name": right,
                           "inclusive": False if exclusive in {"true", "1", "yes"} else True if exclusive in {"false", "0", "no"} else None}
    if "merge" in function or re.search(r"\bmerge\b", source, re.I):
        temporary = _scope_name(scope, bindings.get("temporary"), ("temp", "tmp", "buffer", "merged", "aux"), sequence=True)
        if temporary and temporary != name:
            fields["temporary"] = {"name": temporary, "values": [_plain(value) for value in scope[temporary][:MAX_ITEMS]],
                                   "length": getattr(scope[temporary], "total", None) or len(scope[temporary]),
                                   "truncated": _partial(scope[temporary], step, temporary)}
    if fields:
        model["sorting"] = fields


def _graph_teaching(model: dict, source: str, scope: dict, bindings: dict) -> None:
    nodes = list(map(str, model.get("nodes", [])))
    teaching: dict[str, Any] = {}
    layer = _scope_name(scope, bindings.get("distance"), ("level", "depth", "dist", "distance", "dis", "d"), sequence=True)
    indegree = _scope_name(scope, bindings.get("indegree"), ("indeg", "indegree", "in_degree", "deg"), sequence=True)
    for role, name in (("layers", layer), ("indegree", indegree)):
        if name:
            values = scope[name]
            teaching[role] = {"name": name, "values": {vertex: _plain(values[int(vertex)]) for vertex in nodes if vertex.isdigit() and int(vertex) < len(values)}}
    output = _scope_name(scope, bindings.get("output"), ("order", "topo", "ordering", "result"), sequence=True)
    if output and (indegree or bindings.get("output")) and (bindings.get("output") or output.lower() != "result" or re.search(rf"\b{re.escape(output)}\s*\.\s*(?:append|push_back)\b", source)):
        teaching["output"] = {"name": output, "values": [_plain(value) for value in scope[output][:MAX_ITEMS]]}
    if teaching:
        model["teaching"] = teaching


def build_events(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Index meaningful recorded stops; labels never claim an inferred prune or sift."""
    events = []
    for index, step in enumerate(steps):
        event = step.get("event")
        usage = step.get("usage") or {}
        names = list(dict.fromkeys([*(usage.get("cells") or {}), *(usage.get("next") or {}), *(usage.get("appearing") or {}), *(usage.get("changed") or [])]))
        if event in {"call", "return", "exception", "stopped"}:
            kind = event
            label = f"{event.title()}: {step.get('function') or 'program'}"
        elif names:
            kind, label = "state", "State update: " + ", ".join(names[:4])
        else:
            continue
        events.append({"index": index, "step": step.get("step", index), "line": step.get("line"), "kind": kind, "label": label,
                       "names": names, "depth": step.get("depth", len(step.get("stack") or []))})
    return events


def _window_fields(model: dict, view: dict, scope: dict, previous: dict | None, bindings: dict) -> None:
    left = _scope_name(scope, bindings.get("left") or view.get("left"), ("left", "l", "lo", "start"), scalar=True)
    right = _scope_name(scope, bindings.get("right") or view.get("right"), ("right", "r", "hi", "end"), scalar=True)
    if not left or not right:
        model["notes"] = ["Bind left and right variables to show the active interval."]
        return
    lo, hi = scope[left], scope[right]
    inclusive = view.get("inclusive", True) and bindings.get("right_exclusive") not in {"true", "1", "yes"}
    model["bounds"] = {"left": lo, "right": hi, "inclusive": inclusive}
    model["interval"] = {"low": lo, "high": hi, "inclusive": inclusive}
    model["window"] = {"left": lo, "right": hi, "empty": lo > hi if inclusive else lo >= hi}
    model["markers"] = [{"index": lo, "label": left, "role": "bound"}, {"index": hi, "label": right, "role": "bound"}]
    model["pointer_changes"] = [{"name": name, "before": previous[name], "after": scope[name]} for name in (left, right) if previous and name in previous and previous[name] != scope[name]]
    model["uses"] += [left, right]
    total = _scope_name(scope, bindings.get("total"), ("total", "window_sum", "sum", "curr", "count"), numeric=True)
    if total:
        model["aggregate"] = {"name": total, "value": scope[total]}
        model["readouts"] = [{"label": total, "value": scope[total]}]
        model["uses"].append(total)
    model["notes"] = ["Bounds come from recorded variables. " + ("Both indices are included." if inclusive else "The right boundary is excluded.")]


def _monotonic_fields(model: dict, view: dict, scope: dict, previous: dict | None, bindings: dict) -> None:
    stack_name = model["name"]
    source_name = _scope_name(scope, bindings.get("primary") if bindings.get("primary") != stack_name else None, ("a", "arr", "nums", "values", "heights"), sequence=True)
    source_values = scope.get(source_name) if source_name else None
    indices = isinstance(source_values, list) and all(_int(item) and 0 <= item < len(source_values) for item in model["values"])
    model["role"] = view.get("role", "stack")
    model["direction"] = view.get("direction", "unknown")
    model["storage_kind"] = "indices" if indices else "values"
    model["entries"] = [
        {"position": position, "value": value, **({"index": value, "data_value": _plain(source_values[value])} if indices else {})}
        for position, value in enumerate(model["values"])
    ]
    if indices:
        model["source_name"], model["source_values"] = source_name, [_plain(value) for value in source_values[:MAX_ITEMS]]
        model["source"] = {"name": source_name, "values": model["source_values"]}
        model["uses"].append(source_name)
    old = previous.get(stack_name) if previous else None
    if isinstance(old, list):
        new = scope[stack_name]
        common = 0
        while common < min(len(old), len(new)) and old[common] == new[common]:
            common += 1
        model["delta"] = {"added": [_plain(value) for value in new[common:MAX_ITEMS]], "removed": [_plain(value) for value in old[common:MAX_ITEMS]], "evidence": "snapshot"}


def _fenwick_fields(model: dict, view: dict, scope: dict, step: dict, bindings: dict) -> None:
    index = _scope_name(scope, bindings.get("index") or view.get("index"), ("i", "idx", "index", "pos"), scalar=True)
    current = scope.get(index) if index else None
    model["current"] = current if _int(current) else None
    model["nodes"] = [{"id": i, "index": i, "value": value, "low": i - (i & -i) + 1, "high": i} for i, value in enumerate(model["values"]) if i > 0]
    reads = _read_entries(_current_source(step), scope, _step_language(step))
    model["accesses"] = list(dict.fromkeys(entry["index"] for entry in reads if entry["name"] == model["name"] and "index" in entry))
    if index:
        model["markers"] = [{"index": current, "label": index, "role": "active"}]
        model["uses"].append(index)
    total = _scope_name(scope, bindings.get("total"), ("answer", "ans", "result", "res", "total"), scalar=True)
    if total:
        model["readouts"] = [{"label": total, "value": scope[total]}]
        model["uses"].append(total)
    model["notes"] = ["Node i covers [i − lowbit(i) + 1, i]. Index 0 is storage, not a Fenwick node."]


def _string_model(view: dict, scope: dict, step: dict, bindings: dict) -> dict:
    text_name = _scope_name(scope, bindings.get("text") or view.get("text") or view["variable"], ("text", "s", "haystack"), string=True)
    pattern_name = _scope_name(scope, bindings.get("pattern") or view.get("pattern"), ("pattern", "pat", "p", "needle"), string=True)
    if not text_name or not pattern_name:
        return {"renderer": "string_match", "name": view["variable"], "ready": False}
    text, pattern = scope[text_name], scope[pattern_name]
    model = _base("string_match", text_name, list(text), step)
    model["text"], model["pattern"] = text[:MAX_ITEMS], pattern[:MAX_ITEMS]
    i_name = _scope_name(scope, bindings.get("index"), ("i", "pos", "idx"), scalar=True)
    j_name = _scope_name(scope, bindings.get("column"), ("j", "matched", "k"), scalar=True)
    i, j = scope.get(i_name), scope.get(j_name)
    model["i"], model["j"] = i, j
    model["alignment"] = i - j if _int(i) and _int(j) else None
    model["rows"] = [
        {"name": text_name, "label": "Text", "values": list(text[:MAX_ITEMS]), "length": len(text), "offset": 0, "markers": [{"index": i, "label": i_name}] if i_name else []},
        {"name": pattern_name, "label": "Pattern", "values": list(pattern[:MAX_ITEMS]), "length": len(pattern), "offset": model["alignment"], "markers": [{"index": j, "label": j_name}] if j_name else []},
    ]
    model["uses"] += [pattern_name, *([i_name] if i_name else []), *([j_name] if j_name else [])]
    prefix_name = _scope_name(scope, bindings.get("prefix"), ("prefix", "pi", "lps", "failure", "fail"), sequence=True)
    if prefix_name:
        model["prefix_name"] = prefix_name
        model["prefix"] = [_plain(value) for value in scope[prefix_name][:MAX_ITEMS]]
        model["rows"].append({"name": prefix_name, "label": "Prefix / failure table", "values": model["prefix"], "length": len(scope[prefix_name]), "offset": model["alignment"], "markers": []})
        model["uses"].append(prefix_name)
    model["truncated"] = model["truncated"] or len(pattern) > MAX_ITEMS or _partial(pattern, step, pattern_name) or bool(prefix_name and _partial(scope[prefix_name], step, prefix_name))
    return model


def _string_comparison(model: dict, source: str, scope: dict, bindings: dict, language: str = "python") -> None:
    model.pop("comparison", None)
    rows = model.get("rows") or []
    if len(rows) < 2:
        return
    text_name, pattern_name = rows[0].get("name"), rows[1].get("name")
    text, pattern = scope.get(text_name), scope.get(pattern_name)
    i_name = _scope_name(scope, bindings.get("index"), ("i", "pos", "idx"), scalar=True)
    j_name = _scope_name(scope, bindings.get("column"), ("j", "matched", "k"), scalar=True)
    i, j = scope.get(i_name), scope.get(j_name)
    if not isinstance(text, str) or not isinstance(pattern, str) or not i_name or not j_name or not _int(i) or not _int(j) or not (0 <= i < len(text) and 0 <= j < len(pattern)):
        return
    first = rf"{re.escape(text_name)}\s*\[\s*{re.escape(i_name)}\s*\]"
    second = rf"{re.escape(pattern_name)}\s*\[\s*{re.escape(j_name)}\s*\]"
    code = _strip_source(source, language)
    if re.search(rf"\b(?:{first}\s*(?:==|!=)\s*{second}|{second}\s*(?:==|!=)\s*{first})", code):
        model["comparison"] = {"left": text[i], "right": pattern[j], "equal": text[i] == pattern[j]}


def _trie_model(view: dict, scope: dict, step: dict, bindings: dict) -> dict:
    name, value = view["variable"], scope.get(view["variable"])
    if not _trie_shape(value):
        return {"renderer": "trie", "name": name, "ready": False}
    model = {"renderer": "trie", "name": name, "ready": True, "uses": [name], "nodes": [], "edges": [], "current": None, "path": [], "offset": 0, "length": 0, "truncated": _partial(value, step, name)}
    if isinstance(value, dict):
        pending = [("root", "", value, None, "")]
        while pending and len(model["nodes"]) < MAX_NODES:
            node_id, path, node, parent, char = pending.pop(0)
            terminal = any(bool(node.get(key)) for key in ("end", "terminal", "is_end", "is_word", "word", "count"))
            model["nodes"].append({"id": node_id, "label": char or "root", "path": path, "terminal": terminal})
            if parent is not None:
                model["edges"].append({"source": parent, "target": node_id, "label": char})
            children = node.get("children", node.get("next", node))
            if isinstance(children, dict):
                for char, child in children.items():
                    if isinstance(char, str) and len(char) == 1 and isinstance(child, dict):
                        pending.append((node_id + "/" + char, path + char, child, node_id, char))
        model["truncated"] |= bool(pending)
    else:
        total_name = _scope_name(scope, bindings.get("total"), ("terminal", "end", "is_end", "cnt"), sequence=True)
        terminal = scope.get(total_name) if total_name else []
        reachable, pending = set(), [0]
        while pending and len(reachable) < MAX_NODES:
            node = pending.pop(0)
            if node in reachable or not _int(node) or not 0 <= node < len(value):
                continue
            reachable.add(node)
            model["nodes"].append({"id": str(node), "label": str(node), "path": "", "terminal": bool(terminal[node]) if node < len(terminal) else False})
            row = value[node]
            if not isinstance(row, list):
                continue
            for index, child in enumerate(row[:26]):
                if _int(child) and child > 0:
                    model["edges"].append({"source": str(node), "target": str(child), "label": chr(97 + index)})
                    pending.append(child)
        visible = {node["id"] for node in model["nodes"]}
        model["truncated"] |= bool(pending) or any(edge["target"] not in visible for edge in model["edges"])
        model["edges"] = [edge for edge in model["edges"] if edge["target"] in visible]
        current_name = _scope_name(scope, bindings.get("index"), ("node", "u", "cur", "p"), scalar=True)
        if current_name and str(scope[current_name]) in visible:
            model["current"] = str(scope[current_name])
            model["uses"].append(current_name)
        if total_name:
            model["uses"].append(total_name)
    prefix_name = _scope_name(scope, bindings.get("prefix"), ("prefix", "path"), string=True)
    if prefix_name:
        prefix = scope[prefix_name]
        lookup = {node["path"]: node["id"] for node in model["nodes"]}
        model["path"] = [lookup[prefix[:length]] for length in range(len(prefix) + 1) if prefix[:length] in lookup]
        if prefix in lookup:
            model["current"] = lookup[prefix]
        model["uses"].append(prefix_name)
    char_name = _scope_name(scope, None, ("ch", "char", "character", "c"), string=True)
    model["character"] = scope[char_name] if char_name and len(scope[char_name]) == 1 else None
    model["length"] = len(model["nodes"])
    model["notes"] = ["Terminal markers come from recorded end/terminal/count fields."]
    if model["truncated"]:
        model["notes"].append("Some descendants were not collected or exceed the 60-node view limit.")
    return model


def _base(renderer: str, name: str, values: list, step: dict) -> dict:
    raw = _serialized_scope(step).get(name)
    total = getattr(values, "total", None)
    if isinstance(raw, dict) and _int(raw.get("length")):
        total = raw["length"]
    return {"renderer": renderer, "ready": True, "name": name, "uses": [name], "values": [_plain(value) for value in values[:MAX_ITEMS]],
            "offset": 0, "length": max(len(values), total or 0), "truncated": _partial(values, step, name), "markers": [], "readouts": []}


def _partial(value: Any, step: dict, name: str) -> bool:
    if isinstance(value, (list, str)) and (len(value) > MAX_ITEMS or getattr(value, "total", None)):
        return True
    def clipped(raw: Any, depth: int = 0) -> bool:
        if depth > 6 or not isinstance(raw, dict):
            return False
        if raw.get("truncated") and not raw.get("fill"):
            return True
        return any(clipped(item, depth + 1) for item in raw.get("items", [])) or any(clipped(entry.get("value"), depth + 1) for entry in raw.get("entries", []))
    return clipped(_serialized_scope(step).get(name))


def _read_entries(source: str, scope: dict, language: str = "python") -> list[dict]:
    entries = []
    source = _strip_source(source, language)
    # Plain assignment's destination is not read; augmented assignment reads it.
    assignment = re.search(r"(?<![=!<>])=(?!=)", source)
    read_source = source[assignment.end():] if assignment and not re.search(r"[+\-*/%&|^]$", source[:assignment.start()].rstrip()) else source
    for match in _SUBSCRIPT.finditer(read_source):
        name, first, second = match.groups()
        index = _index_value(first, scope)
        coords = [index]
        if second is not None:
            coords.append(_index_value(second, scope))
        if any(index is None for index in coords):
            continue
        value = _at(scope.get(name), coords)
        if value is _MISSING:
            continue
        if second is None and isinstance(scope.get(name), (list, str)) and _int(index) and index < 0:
            index += len(scope[name])
        entry = {"name": name, "value": _plain(value), "expression": match.group(0)}
        entry["cell" if second is not None else "index"] = coords if second is not None else index
        if entry not in entries:
            entries.append(entry)
    return entries[:MAX_READS]


def _substitute_read(match: re.Match, scope: dict) -> str:
    name, first, second = match.groups()
    coords = [_index_value(first, scope)]
    if second is not None:
        coords.append(_index_value(second, scope))
    value = _at(scope.get(name), coords)
    return str(value) if value is not _MISSING and isinstance(value, (int, float, bool, str)) else match.group(0)


def _write_entries(model: dict, scope: dict, after: dict | None, usage: dict) -> list[dict]:
    entries = []
    for name, marks in (usage.get("cells") or {}).items():
        coordinates = marks.get("cells") or [[index] for index in marks.get("items", [])]
        for coords in coordinates[:MAX_READS]:
            if not isinstance(coords, (list, tuple)):
                continue
            entry = {"name": name, "cell" if len(coords) > 1 else "index": list(coords) if len(coords) > 1 else coords[0]}
            old = _at(scope.get(name), coords)
            new = _at(after.get(name), coords) if after is not None else _model_at(model, name, coords)
            if old is not _MISSING:
                entry["before"] = _plain(old)
            if new is not _MISSING:
                entry["after"] = _plain(new)
            entries.append(entry)
    for name, serialized in (usage.get("next") or {}).items():
        entry = {"name": name, "after": _serialized_plain(serialized)}
        if name in scope:
            entry["before"] = _plain(scope[name])
        entries.append(entry)
    return entries


_MISSING = object()


def _at(value: Any, coordinates: list) -> Any:
    for index in coordinates:
        if isinstance(value, dict):
            if index not in value:
                return _MISSING
            value = value[index]
        elif isinstance(value, (list, str)) and _int(index) and -len(value) <= index < len(value):
            value = value[index]
        else:
            return _MISSING
    return value


def _model_at(model: dict, name: str, coords: list) -> Any:
    if model.get("name") != name or model.get("renderer") in {"segment_tree", "trie", "graph"}:
        return _MISSING
    values = model.get("values") if len(coords) == 1 else model.get("rows")
    if len(coords) > 1 and model.get("renderer") == "grid":
        values = model.get("cells", model.get("values", model.get("rows")))
    return _at(values, coords)


def _index_value(expression: str, scope: dict) -> Any:
    try:
        node = ast.parse(expression.strip(), mode="eval").body
    except (ValueError, SyntaxError):
        return None
    def resolve(node: ast.AST, depth: int = 0) -> Any:
        if depth > 6:
            return None
        if isinstance(node, ast.Constant) and _int(node.value):
            return node.value
        if isinstance(node, ast.Name):
            value = scope.get(node.id)
            return value if _int(value) else None
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd, ast.Invert)):
            value = resolve(node.operand, depth + 1)
            if value is None:
                return None
            return -value if isinstance(node.op, ast.USub) else ~value if isinstance(node.op, ast.Invert) else value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            left, right = resolve(node.left, depth + 1), resolve(node.right, depth + 1)
            if left is None or right is None or abs(left) > 10**12 or abs(right) > 10**12:
                return None
            if isinstance(node.op, (ast.LShift, ast.RShift)) and not 0 <= right <= 64:
                return None
            try:
                return _BINOPS[type(node.op)](left, right)
            except (ArithmeticError, ValueError):
                return None
        return None
    return resolve(node)


def _safe_expression(expression: str, scope: dict) -> Any:
    """Evaluate a small expression over decoded values, never arbitrary Python code."""
    try:
        root = ast.parse(expression, mode="eval").body
    except (ValueError, SyntaxError):
        return _MISSING
    if len(list(ast.walk(root))) > 100:
        return _MISSING

    def scalar(value: Any) -> bool:
        return isinstance(value, (int, float, bool, str)) and (not isinstance(value, str) or len(value) <= 500)

    def resolve(node: ast.AST, depth: int = 0) -> Any:
        if depth > 12:
            return _MISSING
        if isinstance(node, ast.Constant):
            return node.value if scalar(node.value) else _MISSING
        if isinstance(node, ast.Name):
            value = scope.get(node.id, _MISSING)
            return value if scalar(value) or isinstance(value, (list, dict)) else _MISSING
        if isinstance(node, ast.Subscript):
            value, index = resolve(node.value, depth + 1), resolve(node.slice, depth + 1)
            if value is _MISSING or index is _MISSING:
                return _MISSING
            return _at(value, [index])
        if isinstance(node, ast.UnaryOp):
            value = resolve(node.operand, depth + 1)
            if not scalar(value):
                return _MISSING
            if isinstance(node.op, ast.Not):
                return not value
            if not isinstance(value, (int, float)):
                return _MISSING
            if isinstance(node.op, ast.USub):
                return -value
            if isinstance(node.op, ast.UAdd):
                return value
            if isinstance(node.op, ast.Invert) and _int(value):
                return ~value
        if isinstance(node, ast.BinOp):
            left, right = resolve(node.left, depth + 1), resolve(node.right, depth + 1)
            if not scalar(left) or not scalar(right):
                return _MISSING
            if isinstance(left, str) or isinstance(right, str):
                return left + right if isinstance(node.op, ast.Add) and isinstance(left, str) and isinstance(right, str) and len(left) + len(right) <= 500 else _MISSING
            if isinstance(node.op, (ast.LShift, ast.RShift)) and (not _int(right) or not 0 <= right <= 64):
                return _MISSING
            if isinstance(node.op, ast.Pow):
                return left ** right if isinstance(right, int) and 0 <= right <= 16 and abs(left) <= 10**12 else _MISSING
            operation = _BINOPS.get(type(node.op))
            if isinstance(node.op, ast.Div):
                operation = operator.truediv
            return operation(left, right) if operation else _MISSING
        if isinstance(node, ast.BoolOp):
            value = _MISSING
            for child in node.values:
                value = resolve(child, depth + 1)
                if not scalar(value):
                    return _MISSING
                if isinstance(node.op, ast.And) and not value or isinstance(node.op, ast.Or) and value:
                    break
            return value
        if isinstance(node, ast.IfExp):
            condition = resolve(node.test, depth + 1)
            return resolve(node.body if condition else node.orelse, depth + 1) if scalar(condition) else _MISSING
        if isinstance(node, ast.Compare):
            value = resolve(node.left, depth + 1)
            comparisons = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge}
            for operation, child in zip(node.ops, node.comparators):
                other = resolve(child, depth + 1)
                if not scalar(value) or not scalar(other) or type(operation) not in comparisons:
                    return _MISSING
                if not comparisons[type(operation)](value, other):
                    return False
                value = other
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords and len(node.args) <= 16:
            functions = {"min": min, "max": max, "abs": abs}
            name = node.func.id
            if name not in functions or name in scope:
                return _MISSING
            args = [resolve(child, depth + 1) for child in node.args]
            if any(value is _MISSING for value in args):
                return _MISSING
            if len(args) == 1 and isinstance(args[0], list):
                if len(args[0]) > MAX_ITEMS or not all(scalar(value) for value in args[0]):
                    return _MISSING
            elif not all(scalar(value) for value in args):
                return _MISSING
            return functions[name](*args)
        return _MISSING

    try:
        value = resolve(root)
    except (ArithmeticError, TypeError, ValueError):
        return _MISSING
    if isinstance(value, float) and not math.isfinite(value):
        return _MISSING
    if isinstance(value, int) and value.bit_length() > 4096:
        return _MISSING
    return value if scalar(value) else _MISSING


def _plain(value: Any, depth: int = 0) -> Any:
    if _int(value) and abs(value) > 2**53 - 1:
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_plain(item, depth + 1) for item in value[:8]] if depth < 3 else "…"
    if isinstance(value, dict):
        return {str(key): _plain(item, depth + 1) for key, item in list(value.items())[:8]} if depth < 3 else "…"
    return str(value)[:80]


def _serialized_plain(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    if "value" in value:
        return value["value"]
    if "items" in value:
        return [_serialized_plain(item) for item in value["items"][:MAX_ITEMS]]
    return None


def _int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _scope_name(scope: dict, preferred: str | None, candidates: tuple[str, ...], *, scalar: bool = False, string: bool = False, sequence: bool = False, numeric: bool = False) -> str | None:
    for name in ([preferred] if preferred else []) + list(candidates):
        value = scope.get(name)
        if name and ((scalar and _int(value)) or (numeric and isinstance(value, (int, float)) and not isinstance(value, bool)) or (string and isinstance(value, str)) or (sequence and isinstance(value, list))):
            return name
    return None


def _existing_name(scopes: list[dict], preferred: str | None, candidates: tuple[str, ...], **types: bool) -> str | None:
    for name in ([preferred] if preferred else []) + list(candidates):
        if name and any(_scope_name(scope, name, (), **types) for scope in scopes):
            return name
    return None


def _serialized_scope(step: dict) -> dict:
    return {**(step.get("globals") or {}), **(step.get("locals") or {})}


def _current_source(step: dict) -> str:
    return str(step.get("_source_line", step.get("source_line", "")))[:500]


def _step_language(step: dict) -> str:
    return str(step.get("_language", "cpp" if ".cpp" in str(step.get("filename", "")) else "python"))


def _strip_source(source: str, language: str) -> str:
    if language == "cpp":
        from .cpp_source import strip_code
        return strip_code(source)
    lines = source.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    characters = list(source)
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type not in {tokenize.STRING, tokenize.COMMENT}:
                continue
            first = starts[token.start[0] - 1] + token.start[1]
            last = starts[token.end[0] - 1] + token.end[1]
            for index in range(first, min(last, len(characters))):
                if characters[index] not in "\r\n":
                    characters[index] = " "
    except (tokenize.TokenError, IndentationError, IndexError):
        pass
    return "".join(characters)


def _trie_shape(value: Any) -> bool:
    if isinstance(value, dict):
        children = value.get("children", value.get("next", value))
        return isinstance(children, dict) and (not children or any(isinstance(key, str) and len(key) == 1 and isinstance(item, dict) for key, item in children.items()))
    return isinstance(value, list) and bool(value) and all(isinstance(row, list) and len(row) == 26 for row in value[:3])
