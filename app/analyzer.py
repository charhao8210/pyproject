"""Turn a raw trace into what the page draws at every step: the views and their marks."""
from __future__ import annotations

import ast
import re
from dataclasses import replace
from typing import Any, Iterable

from . import lenses, segment_tree
from .array_view import array_visualization, cells_visualization
from .classify import (
    AlgorithmProfile,
    FeatureVisitor,
    classify_cpp,
    classify_python,
    collect_subscripts,
    pair_vertex_position,
    with_focus,
)
from .graph_view import (
    NOT_A_GRAPH_NAMES,
    graph_visualization,
    orient_graphs,
    union_find_parent,
    union_find_visualization,
)
from .grid_view import FRONTIER_NAMES, find_reached_rules, grid_extents, grid_visualization
from .inputs import input_values
from .loops import loop_jumps, loop_ranges
from .recursion import build_recursion_tree
from .usage import front_removed, variable_usage
from .values import (
    decode_scope,
    display_value,
    is_adjacency,
    is_grid,
    is_index,
    is_infinity,
    numeric_array_projection,
    used_rows,
)


def analyze_execution(
    source: str,
    steps: list[dict[str, Any]],
    *,
    language: str = "python",
    extra_views: Iterable[str] = (),
    bindings: dict[str, str] | None = None,
) -> dict[str, Any]:
    decoded: dict[int, Any] = {}
    scopes = [decode_scope(step, decoded) for step in steps]
    shapes = _runtime_shapes(scopes, _edge_id_lists(source))
    if language == "cpp":
        profile = classify_cpp(source, shapes)
    else:
        tree = ast.parse(source, filename="<user_code>", mode="exec")
        features = FeatureVisitor()
        features.visit(tree)
        profile = classify_python(features, shapes)
    profile = with_focus(profile, source, language)
    profile = replace(profile, subscripts=collect_subscripts(source), pair_vertex=pair_vertex_position(source))

    parent_name, first_vertex = union_find_parent(source)
    if parent_name is not None:
        profile = AlgorithmProfile(
            "union_find",
            "Union-find (disjoint sets)",
            "dsu",
            0.9,
            ("find function", f"parent array {parent_name}", "self-parent initialisation"),
        )

    # Every view the user can pick is computed up front, so switching views needs no re-run.
    catalog = _view_catalog(scopes, steps, set(extra_views))
    inferred_profile = profile
    bindings = {key: value for key, value in (bindings or {}).items() if isinstance(value, str) and value}
    catalog.extend(lenses.extend_catalog(source, scopes, steps, language=language, bindings=bindings))
    manual_mode = bindings.get("mode", "auto")
    primary = bindings.get("primary")
    manual_renderers = {"dp": "grid", "sorting": "array", "graph": "graph", "dsu": "dsu"}
    if manual_mode in manual_renderers and primary:
        renderer = manual_renderers[manual_mode]
        if manual_mode == "dp" and not any(is_grid(scope.get(primary)) for scope in scopes):
            renderer = "array"
        manual_id = f"{renderer}:{primary}"
        if not any(item["id"] == manual_id for item in catalog):
            catalog.insert(0, {"id": manual_id, "renderer": renderer, "variable": primary})
        for item in catalog:
            if item["id"] == manual_id:
                item.pop("pending", None)
        profile = replace(profile, kind="dynamic_programming" if manual_mode == "dp" else manual_mode,
                          name={"dp": "Dynamic programming", "sorting": "Sorting", "graph": "Graph", "dsu": "Union-find"}[manual_mode],
                          renderer=renderer, focus=(primary,), confidence=1.0, evidence=("chosen by you",))
    if parent_name is not None and any(isinstance(scope.get(parent_name), list) for scope in scopes):
        catalog.insert(
            0,
            {"id": f"dsu:{parent_name}", "renderer": "dsu", "variable": parent_name, "first": first_vertex},
        )

    # A recursive segment tree (`tree[id*2]`, `tree[id*2+1]` over `[l, r]`) is drawn as the tree.
    segment_spec = segment_tree.detect(source, language)
    segment_layout = segment_tree.layout(segment_spec, steps, scopes) if segment_spec else None
    segment_paths: list[list[int]] = []
    source_lines = source.split("\n")
    if segment_layout is not None:
        segment_paths = segment_tree.call_paths(segment_spec, steps, scopes)
        catalog.insert(0, {
            "id": f"segment_tree:{segment_spec['array']}",
            "renderer": "segment_tree",
            "variable": segment_spec["array"],
            "layout": segment_layout,
        })
        if parent_name is None:
            profile = AlgorithmProfile(
                "segment_tree",
                "Segment tree",
                "segment_tree",
                0.9,
                (f"{segment_spec['array']}[{segment_spec['node']}*2] children", "recursive range split"),
            )
    recursion_tree, recursion_steps = (
        build_recursion_tree(steps, language)
        if any(view["renderer"] == "recursion_tree" for view in catalog)
        else (None, [])
    )

    if language == "cpp" and recursion_steps:
        for index, step in enumerate(steps):
            step["_frame_id"] = recursion_steps[index].get("current")
    usage = variable_usage(source, language, steps, scopes)
    loops = loop_jumps(steps, loop_ranges(source, language))
    inputs = input_values(source, language, steps)
    extents = grid_extents(scopes)
    profile = replace(profile, reached_rules=find_reached_rules(scopes))
    last_ready: dict[str, dict[str, Any]] = {}
    previous: dict[str, dict[str, Any]] = {}
    # The "infinity" placeholder values seen in each array so far (`_mark_infinite`).
    sentinels: dict[str, set[Any]] = {}
    spells_infinity = bool(_INFINITY_SPELLINGS.search(source))
    for index, (step, scope) in enumerate(zip(steps, scopes)):
        line = step.get("line")
        step["_source_line"] = source_lines[line - 1] if isinstance(line, int) and 0 < line <= len(source_lines) else ""
        step["_language"] = language
        step["usage"] = usage[index]
        step["loop"] = loops[index]
        step["inputs"] = inputs[index]
        input_names = {entry["name"] for entry in inputs[index]}
        automatic = _visualization_for(profile, scope, step, extents)
        if profile.renderer == "call_tree" and recursion_steps and recursion_tree and recursion_tree["nodes"]:
            # A function calling itself reads best as its recursion tree: every call with its
            # arguments (`fib(4)`, `fib(3)`) and returned value, not a chain of bare `fib()`.
            automatic = {"renderer": "recursion_tree", "ready": True, **recursion_steps[index]}
        visualization = _carry(AUTO_VIEW, automatic, last_ready, step)
        _drop_input_readouts(visualization, input_names)
        previous_scope = scopes[index - 1] if index else None
        _mark_writes(visualization, previous.get(AUTO_VIEW), scope, previous_scope)
        _mark_line_reads(visualization, step, scope, source_lines, language)
        _mark_infinite(visualization, sentinels, spells_infinity)
        previous[AUTO_VIEW] = visualization
        step["visualization"] = visualization

        views: dict[str, dict[str, Any]] = {}
        for view in catalog:
            if view.get("pending"):
                continue
            recursion_state = recursion_steps[index] if recursion_steps else None
            if view["renderer"] == "segment_tree":
                line = step.get("line")
                line_text = source_lines[line - 1] if isinstance(line, int) and 1 <= line <= len(source_lines) else ""
                model = segment_tree.model(
                    segment_spec, segment_layout, scope, step, segment_paths[index], line_text, language
                )
            else:
                if view["renderer"] in lenses.RENDERERS:
                    model = lenses.view_model(view, scope, step, previous_scope, bindings=bindings)
                else:
                    model = _view_model(view, profile, scope, step, recursion_state, language, extents)
            model = _carry(view["id"], model, last_ready, step)
            _drop_input_readouts(model, input_names)
            _mark_writes(model, previous.get(view["id"]), scope, previous_scope)
            _mark_line_reads(model, step, scope, source_lines, language)
            _mark_infinite(model, sentinels, spells_infinity)
            previous[view["id"]] = model
            views[view["id"]] = model
        step["views"] = views
        if profile.renderer in {"dsu", "segment_tree"} and catalog[0]["renderer"] == profile.renderer:
            step["visualization"] = views[catalog[0]["id"]]

    orient_graphs(steps)
    # Pair effects in the same live frame, including lines whose nested calls have returned.
    frame_steps: dict[tuple[int, str, int | None], int] = {}
    after_scopes: dict[int, dict[str, Any]] = {}
    after_indices: dict[int, int] = {}
    for index, step in enumerate(steps):
        depth = int(step.get("depth", len(step.get("stack") or [])))
        key = (depth, str(step.get("function")), step.get("_frame_id"))
        for stale in [item for item in frame_steps if item[0] > depth or key[2] is not None and item[0] == depth and item[2] != key[2]]:
            frame_steps.pop(stale)
        if step.get("event") == "call":
            frame_steps.pop(key, None)
        if key in frame_steps:
            after_scopes[frame_steps[key]] = scopes[index]
            after_indices[frame_steps[key]] = index
        frame_steps[key] = index
    _show_line_effects(steps, after_indices)
    for index, (step, scope) in enumerate(zip(steps, scopes)):
        step["_after_scope"] = after_scopes.get(index)
        models = [step["visualization"], *step["views"].values()]
        for model in models:
            lenses.enrich_model(model, step, scope, scopes[index - 1] if index else None, bindings=bindings)
        step.pop("_source_line", None)
        step.pop("_language", None)
        step.pop("_after_scope", None)
        step.pop("_frame_id", None)

    # The profile can name a renderer whose data never shows up (a 1D `dp` for a
    # "DP table"); Auto then falls back to the first view that draws something.
    if not any(step["visualization"].get("ready") for step in steps):
        fallback = next(
            (
                view["id"]
                for view in catalog
                if view["renderer"] != "execution"
                and not view.get("pending")
                and any(step["views"][view["id"]].get("ready") for step in steps)
            ),
            None,
        )
        if fallback is None and any(view["renderer"] == "execution" for view in catalog):
            fallback = "execution"
        if fallback is not None:
            for step in steps:
                step["visualization"] = step["views"][fallback]

    selected = None
    if manual_mode != "auto":
        target_renderer = manual_renderers.get(manual_mode, manual_mode)
        if manual_mode == "dp" and primary:
            target_renderer = "grid" if any(is_grid(scope.get(primary)) for scope in scopes) else "array"
        target_variable = bindings.get("stack", primary) if manual_mode == "monotonic" else bindings.get("text", primary) if manual_mode == "string_match" else primary
        selected = next((item for item in catalog if item["renderer"] == target_renderer
                         and (not target_variable or item.get("variable") == target_variable)), None)
    elif profile.kind in {"generic", "array_processing", "matrix_processing", "sorting"}:
        selected = next((item for item in catalog if item.get("preferred")), None)
    if selected is not None and not any(step["views"].get(selected["id"], {}).get("ready") for step in steps):
        selected = None
    if selected is not None:
        for step in steps:
            if selected["id"] in step["views"]:
                step["visualization"] = step["views"][selected["id"]]
        manual_names = {"dp": "Dynamic programming", "sorting": "Sorting", "graph": "Graph",
                        "dsu": "Union-find", "segment_tree": "Segment tree"}
        manual_kinds = {"dp": "dynamic_programming", "dsu": "union_find"}
        profile = replace(profile, renderer=selected["renderer"],
                          kind=manual_kinds.get(manual_mode, manual_mode) if manual_mode != "auto" else selected["renderer"],
                          name=manual_names.get(manual_mode, selected.get("label", selected["renderer"].replace("_", " ").title())),
                          evidence=("chosen by you",) if manual_mode != "auto" else ("algorithm operation pattern",))
    elif manual_mode != "auto":
        profile = inferred_profile
    result = profile.as_dict()
    result["events"] = lenses.build_events(steps)
    result["bindings"] = bindings
    result["manual_applied"] = manual_mode != "auto" and selected is not None
    result["binding_warnings"] = (
        [f"Cannot apply {manual_mode} to {primary or 'the available variables'}; showing the automatic view. Check the variable pairing and source structure."]
        if manual_mode != "auto" and selected is None else []
    )
    result["variables"] = sorted({name for scope in scopes for name in scope if not name.startswith("__")})
    result["views"] = catalog
    # What Auto actually draws (after any fallback), for the view picker's label.
    drawn = [step["visualization"].get("renderer") for step in steps if step["visualization"].get("ready")]
    result["auto_renderer"] = (
        "dsu" if profile.renderer == "dsu" else max(set(drawn), key=drawn.count) if drawn else "execution"
    )
    if recursion_tree is not None:
        result["recursion_tree"] = recursion_tree
    if language == "cpp":
        result["method"] = "C++ source and runtime-state heuristics"
    return result


_VERTEX_READ = re.compile(r"(?<![\w.])([A-Za-z_]\w*)\s*\[\s*([A-Za-z_]\w*|\d+)\s*\](?!\s*\[)")


def _mark_line_reads(
    model: dict[str, Any],
    step: dict[str, Any],
    scope: dict[str, Any],
    source_lines: list[str],
    language: str,
) -> None:
    """Per-vertex entries the step's line reads (`if (dis[n] == 0)`): the vertex is marked
    Reading and the entry printed with its value, `dis[n] = 3`."""
    if model.get("renderer") != "graph" or not model.get("ready") or model.get("layout") == "forest":
        return
    line = step.get("line")
    text = source_lines[line - 1] if isinstance(line, int) and 1 <= line <= len(source_lines) else ""
    if language == "cpp":
        text = re.sub(r"//.*$", "", text)
    else:
        text = text.split("#", 1)[0]
    nodes = set(model.get("nodes") or [])
    reading = []
    for match in _VERTEX_READ.finditer(text):
        name, index_text = match.groups()
        values = scope.get(name)
        index = int(index_text) if index_text.isdigit() else scope.get(index_text)
        if not isinstance(values, list) or not is_index(index) or not 0 <= index < len(values):
            continue
        value = values[index]
        if str(index) not in nodes or not _is_single_value(value):
            continue
        entry = {"vertex": str(index), "text": f"{name}[{index_text}] = {display_value(value, language)}"}
        if entry not in reading:
            reading.append(entry)
    model["reading"] = reading


def _is_single_value(value: Any) -> bool:
    return isinstance(value, (int, float, str, bool)) and not isinstance(value, list)


def _show_line_effects(steps: list[dict[str, Any]], after_indices: dict[int, int] | None = None) -> None:
    """Draw each step's views as they are once its highlighted line has run.

    A stop comes before its line runs, so the state recorded there misses what that line does:
    `vis[v] = true` would only show as visited one step later. So each step shows the next
    stop's state, whose `written` / `added` marks are exactly that line's writes.
    The current-line view keeps its own step, a segment tree keeps the nodes this line reads,
    and the names either state draws stay out of Variables. `at_step` is the step drawn.
    """
    own = [(step["visualization"], step["views"]) for step in steps]
    for index, step in enumerate(steps):
        after = (after_indices or {}).get(index, index + 1) if step.get("event") == "line" else index + 1
        if after >= len(steps) or step.get("event") in {"exception", "stopped"}:
            continue
        mine_auto, mine_views = own[index]
        next_auto, next_views = own[after]
        step["visualization"] = _after_line(mine_auto, next_auto, after)
        step["views"] = {
            view_id: _after_line(model, next_views.get(view_id, model), after)
            for view_id, model in mine_views.items()
        }


def _after_line(mine: dict[str, Any], after: dict[str, Any], after_index: int) -> dict[str, Any]:
    if mine.get("renderer") in {"execution", "recursion_tree", "call_tree"} or after.get("renderer") != mine.get("renderer"):
        return mine
    # A carried state is the data a returned call left behind, not what this line did here:
    # `main()` would otherwise draw main's final table before the input is even read.
    if after.get("carried"):
        return mine
    shown = {**after, "at_step": after_index}
    if mine.get("renderer") == "segment_tree":
        # Node values after the line; where the code is (its call path) and what the line reads
        # stay this step's, since the next stop may already be back in the caller.
        for key in ("reading", "current", "path"):
            if key in mine:
                shown[key] = mine[key]
    if mine.get("renderer") == "graph":
        # What the line reads (`dis[n]`) is read before it runs, so it is this step's.
        shown["reading"] = mine.get("reading", [])
    uses = [*after.get("uses", []), *mine.get("uses", [])]
    if uses:
        shown["uses"] = list(dict.fromkeys(uses))
    return shown


def _drop_input_readouts(model: dict[str, Any], input_names: set[str]) -> None:
    """Input values (`n`, `k`) are shown once in the input row, not again as a view's readout."""
    readouts = model.get("readouts")
    if not readouts or not input_names:
        return
    dropped = {readout["label"] for readout in readouts} & input_names
    if not dropped:
        return
    kept = [readout for readout in readouts if readout["label"] not in dropped]
    if kept:
        model["readouts"] = kept
    else:
        del model["readouts"]
    # No longer drawn by the view, so the input row shows it.
    model["uses"] = [name for name in model.get("uses", []) if name not in dropped]


AUTO_VIEW = "auto"
MAX_VIEW_VARIABLES = 6
_VARIABLE_RENDERERS = ("grid", "array", "cells", "graph")


def _view_catalog(
    scopes: list[dict[str, Any]],
    steps: list[dict[str, Any]],
    requested: set[str] | None = None,
) -> list[dict[str, Any]]:
    """List every (renderer, variable) pair whose data shape appears somewhere in the trace.

    All of them can be picked, but only the first `MAX_VIEW_VARIABLES` per renderer (and any
    `requested` by id) are computed for every step; the rest are `pending`, and picking one
    runs the program again asking for it (`DebugRequest.views`), so a seventh array is
    reachable without every trace paying for every view.
    """
    found: dict[str, list[str]] = {renderer: [] for renderer in _VARIABLE_RENDERERS}

    def add(renderer: str, name: str) -> None:
        if name not in found[renderer]:
            found[renderer].append(name)

    for scope in scopes:
        for name, value in scope.items():
            if name.startswith("__"):
                continue
            if is_grid(value):
                add("grid", name)
            # Any list can be shown as a row of cells; rows of a grid show as compact lists.
            # A string shows one character per cell.
            if (isinstance(value, list) and value) or (isinstance(value, str) and len(value) >= 2):
                add("cells", name)
            if numeric_array_projection(value) is not None:
                add("array", name)
            if is_adjacency(value, name):
                add("graph", name)

    catalog = []
    for renderer in _VARIABLE_RENDERERS:
        for position, name in enumerate(found[renderer]):
            view_id = f"{renderer}:{name}"
            view = {"id": view_id, "renderer": renderer, "variable": name}
            if position >= MAX_VIEW_VARIABLES and view_id not in (requested or set()):
                view["pending"] = True
            catalog.append(view)
    if any(len(step.get("stack") or []) >= 2 for step in steps):
        catalog.append({"id": "recursion_tree", "renderer": "recursion_tree", "variable": None})
        catalog.append({"id": "call_tree", "renderer": "call_tree", "variable": None})
    catalog.append({"id": "execution", "renderer": "execution", "variable": None})
    return catalog


def _view_model(
    view: dict[str, Any],
    profile: AlgorithmProfile,
    scope: dict[str, Any],
    step: dict[str, Any],
    recursion_state: dict[str, Any] | None,
    language: str,
    extents: dict[str, tuple[int, int]] | None = None,
) -> dict[str, Any]:
    renderer, name = view["renderer"], view["variable"]
    if renderer == "grid":
        return grid_visualization(scope, step, name, extents, dict(profile.reached_rules))
    if renderer == "array":
        return array_visualization(scope, profile, name, extents)
    if renderer == "cells":
        return cells_visualization(scope, profile, name, language, extents)
    if renderer == "graph":
        return graph_visualization(scope, name, profile.pair_vertex)
    if renderer == "dsu":
        return union_find_visualization(scope, name, view.get("first", 0))
    if renderer == "recursion_tree":
        return {"renderer": "recursion_tree", **(recursion_state or {"current": None, "uses": []})}
    if renderer == "call_tree":
        return _call_tree_visualization(step)
    return _execution_visualization(step)


def _carry(
    key: str,
    visualization: dict[str, Any],
    last_ready: dict[str, dict[str, Any]],
    step: dict[str, Any],
) -> dict[str, Any]:
    """Keep showing a view's last ready state while its data is out of scope."""
    if visualization.get("ready"):
        last_ready[key] = visualization
        return visualization
    if key not in last_ready:
        return visualization
    carried = dict(last_ready[key])
    carried["carried"] = True
    # Carried state was drawn from an earlier scope, so it hides no current variables.
    carried["uses"] = []
    carried["written"] = []
    carried.pop("added", None)
    carried["event"] = step.get("event")
    renderer = carried.get("renderer")
    if renderer == "grid":
        carried["active"] = []
        carried["frontier"] = []
    elif renderer in {"array", "cells"}:
        carried["markers"] = []
        carried.pop("interval", None)
        carried.pop("readouts", None)
    elif renderer == "graph":
        carried["current"] = None
    return carried


def _mark_writes(
    model: dict[str, Any],
    previous: dict[str, Any] | None,
    scope: dict[str, Any],
    previous_scope: dict[str, Any] | None,
) -> None:
    """Record which entries changed since the previous step (written, as opposed to read).

    Entries a container gained at its end (a push) are `added`, not written; the step whose
    line pushed them draws them blue (`_show_line_effects`), and the next one draws them plain.
    A queue that lost its front (`q.pop()`) is compared after that shift, so the entries that
    only moved down are not marked either.
    """
    renderer = model.get("renderer")
    if renderer == "segment_tree":
        # Node values sit in layout order, which never changes within a trace.
        old = previous.get("values") if previous and previous.get("ready") else None
        model["written"] = [
            position for position, value in enumerate(model.get("values") or [])
            if old is not None and position < len(old) and old[position] != value
        ] if model.get("ready") and not model.get("carried") else []
        return
    if renderer not in {"grid", "array", "cells"}:
        return
    comparable = (
        model.get("ready")
        and not model.get("carried")
        and previous is not None
        and previous.get("ready")
        and previous.get("name") == model.get("name")
    )
    if not comparable:
        model["written"] = []
        return
    if renderer == "grid":
        old_rows = previous["rows"]
        model["written"] = [
            {"row": row_index, "column": column_index}
            for row_index, row in enumerate(model["rows"])
            for column_index, cell in enumerate(row)
            if row_index < len(old_rows)
            and column_index < len(old_rows[row_index])
            and old_rows[row_index][column_index] != cell
        ]
        return
    old_values = previous["values"]
    values = model["values"]
    # Only a container whose real length changed can have gained or lost entries; a fixed C++
    # array keeps its length, and its drawn length (cut at the last used entry) says nothing.
    raw = scope.get(model["name"])
    old_raw = (previous_scope or {}).get(model["name"])
    if not (isinstance(raw, list) and isinstance(old_raw, list) and len(raw) != len(old_raw)) or model.get("truncated"):
        model["written"] = [
            index for index, value in enumerate(values) if index >= len(old_values) or old_values[index] != value
        ]
        return
    removed = front_removed(old_raw, raw)
    if removed or values[: len(old_values)] == old_values:
        model["written"] = []
        model["added"] = list(range(max(len(old_values) - removed, 0), len(values)))
        return
    model["written"] = [
        index for index, value in enumerate(values) if index >= len(old_values) or old_values[index] != value
    ]


_INFINITY_SPELLINGS = re.compile(
    r"\b(?:INF|inf|oo|INFINITY|LLINF|INT_MAX|LLONG_MAX|LONG_MAX|INT64_MAX)\b"
    r"|0x3[fF]3[fF]3[fF]3[fF]|\b1e(?:9|18|15|17)\b|10\s*\*\*\s*(?:9|18)|float\(\s*['\"]inf['\"]\s*\)|math\.inf"
)


def _mark_infinite(model: dict[str, Any], sentinels: dict[str, set[Any]], spells_infinity: bool) -> None:
    """Entries holding an "infinity" placeholder (`INF = 1e9` in a dp or dist array).

    Needs three pieces of evidence, so ordinary large numbers (`prices = [1e9, 1e9, 3]`) stay
    numbers: the code spells an infinity (`INF`, `LLONG_MAX`, `1e18`, `0x3f3f3f3f`), the value is
    a usual INF constant, and at some step it was every nonzero entry of the array, at least two
    (`[INF] * n`, `dist(n + 1, LLONG_MAX)`, a fill loop still running). Once known it stays known.
    Bars draw these apart instead of letting 10^9 flatten every real value.
    """
    if model.get("renderer") != "array" or not model.get("ready"):
        return
    values = model.get("captured_values") or model.get("values") or []
    known = sentinels.setdefault(str(model.get("name")), set())
    nonzero = [value for value in values if value != 0]
    if spells_infinity and len(nonzero) >= 2 and len(set(nonzero)) == 1 and is_infinity(nonzero[0]):
        known.add(nonzero[0])
    infinite = [index for index, value in enumerate(values) if value in known or value == float("inf")]
    if infinite:
        model["infinite"] = infinite


def _edge_id_lists(source: str) -> frozenset[str]:
    """Lists filled with edge numbers (`g[a].push_back(edges.size())`): their rows are not neighbours."""
    return frozenset(
        re.findall(r"\b([A-Za-z_]\w*)\s*\[[^\]]*\]\s*\.\s*(?:push_back|emplace_back|append)\s*\(\s*(?:len\s*\(\s*\w+\s*\)|\w+\s*\.\s*size\s*\(\s*\))\s*\)", source)
    )


def _runtime_shapes(scopes: list[dict[str, Any]], edge_id_lists: frozenset[str] = frozenset()) -> set[str]:
    shapes: set[str] = set()
    for scope in scopes:
        for name, value in scope.items():
            # A queue or stack of (row, col) pairs is a frontier, not a table.
            if is_grid(value) and name.lower() not in FRONTIER_NAMES:
                shapes.add("matrix")
                # Rows of two are usually (value, index) pairs, which read best as bars.
                if all(len(row) >= 3 for row in used_rows(value)):
                    shapes.add("wide_matrix")
                if name.lower() not in {"vis", "visited", "seen", "dp"}:
                    shapes.add("grid")
            if numeric_array_projection(value) is not None:
                shapes.add("numeric_array")
            if is_adjacency(value, name) and name.lower() not in NOT_A_GRAPH_NAMES and name not in edge_id_lists:
                shapes.add("graph")
                # Rows of different lengths: a real adjacency list, not a numeric table.
                if isinstance(value, list) and len({len(row) for row in value}) > 1:
                    shapes.add("adjacency_list")
        if shapes >= {"matrix", "wide_matrix", "grid", "numeric_array", "graph", "adjacency_list"}:
            break
    return shapes


def _visualization_for(
    profile: AlgorithmProfile,
    scope: dict[str, Any],
    step: dict[str, Any],
    extents: dict[str, tuple[int, int]] | None = None,
) -> dict[str, Any]:
    if profile.renderer == "grid":
        return grid_visualization(scope, step, None, extents, dict(profile.reached_rules))
    if profile.renderer == "array":
        return array_visualization(scope, profile, None, extents)
    if profile.renderer == "graph":
        return graph_visualization(scope, None, profile.pair_vertex)
    if profile.renderer == "call_tree":
        return _call_tree_visualization(step)
    return _execution_visualization(step)


def _call_tree_visualization(step: dict[str, Any]) -> dict[str, Any]:
    frames = step.get("stack", [])
    # Deep Python stacks keep only the outermost and innermost frames; `hidden` counts the rest.
    return {
        "renderer": "call_tree",
        "ready": bool(frames),
        "frames": frames,
        "hidden": max(0, int(step.get("depth", len(frames))) - len(frames)),
    }


def _execution_visualization(step: dict[str, Any]) -> dict[str, Any]:
    return {
        "renderer": "execution",
        "event": step.get("event"),
        "line": step.get("line"),
        "function": step.get("function"),
    }
