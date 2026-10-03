from __future__ import annotations

import ast
import re
from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable

from . import segment_tree
from .loops import loop_jumps, loop_ranges
from .recursion import build_recursion_tree
from .serializer import MAX_ITEMS
from .inputs import input_values
from .usage import front_removed, variable_usage


MAX_VISUAL_ROWS = 30
MAX_VISUAL_COLUMNS = 40
MAX_VISUAL_ITEMS = 60


@dataclass(frozen=True)
class AlgorithmProfile:
    kind: str
    name: str
    renderer: str
    confidence: float
    evidence: tuple[str, ...]
    # Arrays the loops write, most deeply nested first: what an array view should draw.
    focus: tuple[str, ...] = ()
    # (container, index variable) for every `a[i]` in the source: an index marker is drawn
    # only on a container that variable indexes (`l[i]` does not put `i` on `v`).
    subscripts: frozenset[tuple[str, str]] = frozenset()

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "renderer": self.renderer,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "method": "AST and runtime-state heuristics",
        }


class _FeatureVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()
        self.method_calls: set[str] = set()
        self.direct_calls: set[str] = set()
        self.recursive_functions: set[str] = set()
        self.max_loop_depth = 0
        self.while_count = 0
        self.max_subscript_depth = 0
        self.subscript_writes = 0
        self._loop_depth = 0
        self._function_stack: list[str] = []

    def visit_Name(self, node: ast.Name) -> None:
        self.names.add(node.id.lower())

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function_stack.append(node.name)
        self.generic_visit(node)
        self._function_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute):
            self.method_calls.add(node.func.attr.lower())
        elif isinstance(node.func, ast.Name):
            name = node.func.id
            self.direct_calls.add(name.lower())
            if self._function_stack and name == self._function_stack[-1]:
                self.recursive_functions.add(name)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self._visit_loop(node)

    def visit_While(self, node: ast.While) -> None:
        self.while_count += 1
        self._visit_loop(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        depth = 1
        value = node.value
        while isinstance(value, ast.Subscript):
            depth += 1
            value = value.value
        self.max_subscript_depth = max(self.max_subscript_depth, depth)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.subscript_writes += sum(
            isinstance(target, (ast.Subscript, ast.Tuple))
            for target in node.targets
        )
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.target, ast.Subscript):
            self.subscript_writes += 1
        self.generic_visit(node)

    def _visit_loop(self, node: ast.For | ast.While) -> None:
        self._loop_depth += 1
        self.max_loop_depth = max(self.max_loop_depth, self._loop_depth)
        self.generic_visit(node)
        self._loop_depth -= 1


def analyze_execution(
    source: str,
    steps: list[dict[str, Any]],
    *,
    language: str = "python",
) -> dict[str, Any]:
    decoded: dict[int, Any] = {}
    scopes = [_decode_scope(step, decoded) for step in steps]
    shapes = _runtime_shapes(scopes, _edge_id_lists(source))
    if language == "cpp":
        profile = _classify_cpp(source, shapes)
    else:
        tree = ast.parse(source, filename="<user_code>", mode="exec")
        features = _FeatureVisitor()
        features.visit(tree)
        profile = _classify(features, shapes)
    profile = _with_focus(profile, source, language)
    profile = replace(profile, subscripts=_subscripts(source))

    parent_name, first_vertex = _union_find_parent(source)
    if parent_name is not None:
        profile = AlgorithmProfile(
            "union_find",
            "Union-find (disjoint sets)",
            "dsu",
            0.9,
            ("find function", f"parent array {parent_name}", "self-parent initialisation"),
        )

    # Every view the user can pick is computed up front, so switching views needs no re-run.
    catalog = _view_catalog(scopes, steps)
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

    usage = variable_usage(source, language, steps, scopes)
    loops = loop_jumps(steps, loop_ranges(source, language))
    inputs = input_values(source, language, steps)
    extents = _grid_extents(scopes)
    last_ready: dict[str, dict[str, Any]] = {}
    previous: dict[str, dict[str, Any]] = {}
    # The "infinity" placeholder values seen in each array so far (`_mark_infinite`).
    sentinels: dict[str, set[Any]] = {}
    for index, (step, scope) in enumerate(zip(steps, scopes)):
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
        _mark_infinite(visualization, sentinels)
        previous[AUTO_VIEW] = visualization
        step["visualization"] = visualization

        views: dict[str, dict[str, Any]] = {}
        for view in catalog:
            recursion_state = recursion_steps[index] if recursion_steps else None
            if view["renderer"] == "segment_tree":
                line = step.get("line")
                line_text = source_lines[line - 1] if isinstance(line, int) and 1 <= line <= len(source_lines) else ""
                model = segment_tree.model(
                    segment_spec, segment_layout, scope, step, segment_paths[index], line_text, language
                )
            else:
                model = _view_model(view, profile, scope, step, recursion_state, language, extents)
            model = _carry(view["id"], model, last_ready, step)
            _drop_input_readouts(model, input_names)
            _mark_writes(model, previous.get(view["id"]), scope, previous_scope)
            _mark_line_reads(model, step, scope, source_lines, language)
            _mark_infinite(model, sentinels)
            previous[view["id"]] = model
            views[view["id"]] = model
        step["views"] = views
        if profile.renderer in {"dsu", "segment_tree"} and catalog[0]["renderer"] == profile.renderer:
            step["visualization"] = views[catalog[0]["id"]]

    _orient_graphs(steps)
    _show_line_effects(steps)

    # The profile can name a renderer whose data never shows up (a 1D `dp` for a
    # "DP table"); Auto then falls back to the first view that draws something.
    if not any(step["visualization"].get("ready") for step in steps):
        fallback = next(
            (
                view["id"]
                for view in catalog
                if view["renderer"] != "execution"
                and any(step["views"][view["id"]].get("ready") for step in steps)
            ),
            None,
        )
        if fallback is None and any(view["renderer"] == "execution" for view in catalog):
            fallback = "execution"
        if fallback is not None:
            for step in steps:
                step["visualization"] = step["views"][fallback]

    result = profile.as_dict()
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
        if not isinstance(values, list) or not _is_index(index) or not 0 <= index < len(values):
            continue
        value = values[index]
        if str(index) not in nodes or not _is_single_value(value):
            continue
        entry = {"vertex": str(index), "text": f"{name}[{index_text}] = {_display_value(value, language)}"}
        if entry not in reading:
            reading.append(entry)
    model["reading"] = reading


def _is_single_value(value: Any) -> bool:
    return isinstance(value, (int, float, str, bool)) and not isinstance(value, list)


def _show_line_effects(steps: list[dict[str, Any]]) -> None:
    """Draw each step's views as they are once its highlighted line has run.

    A stop comes before its line runs, so the state recorded there misses what that line does:
    `vis[v] = true` only showed as visited one step later (the user's complaint). Each step now
    shows the next stop's state, whose `written` / `added` marks are exactly that line's writes.
    The current-line view keeps its own step, a segment tree keeps the nodes this line reads,
    and the names either state draws stay out of Variables. `at_step` is the step drawn.
    """
    own = [(step["visualization"], step["views"]) for step in steps]
    for index, step in enumerate(steps):
        after = index + 1
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
    if mine.get("renderer") == "execution" or after.get("renderer") != mine.get("renderer"):
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


def _orient_graphs(steps: list[dict[str, Any]]) -> None:
    """Decide once per trace whether each graph is directed, and draw undirected edges once.

    An undirected adjacency list stores every edge both ways (`adj[a].push_back(b)` and
    `adj[b].push_back(a)`); a directed one (`adj[a].push_back({b, c})` only) does not. The
    fullest state of the graph decides, since an edge is half-stored between its two pushes.
    Parallel edges (`1 → 3` twice) are kept: the view bends them apart.
    """
    models = []
    seen: set[int] = set()
    for step in steps:
        for model in (step.get("visualization"), *(step.get("views") or {}).values()):
            if (
                isinstance(model, dict)
                and model.get("renderer") == "graph"
                and model.get("ready")
                and model.get("layout") != "forest"
                and id(model) not in seen
            ):
                seen.add(id(model))
                models.append(model)
    fullest: dict[str, list[dict[str, str]]] = {}
    for model in models:
        name = str(model.get("name"))
        if len(model.get("edges") or []) >= len(fullest.get(name, [])):
            fullest[name] = model.get("edges") or []
    directed = {name: not _symmetric(edges) for name, edges in fullest.items() if edges}
    for model in models:
        name = str(model.get("name"))
        if name not in directed:
            continue
        model["directed"] = directed[name]
        if not directed[name]:
            model["edges"] = _undirected_edges(model.get("edges") or [])


def _edge_key(edge: dict[str, str], reverse: bool = False) -> tuple[str, str, Any]:
    ends = (edge["target"], edge["source"]) if reverse else (edge["source"], edge["target"])
    return (*ends, edge.get("weight"))


def _symmetric(edges: list[dict[str, str]]) -> bool:
    counts: dict[tuple[str, str, Any], int] = {}
    for edge in edges:
        counts[_edge_key(edge)] = counts.get(_edge_key(edge), 0) + 1
    return all(counts.get((target, source, weight), 0) == count for (source, target, weight), count in counts.items())


def _undirected_edges(edges: list[dict[str, str]]) -> list[dict[str, str]]:
    """Each stored pair `a → b`, `b → a` once; two edges between the same vertices stay two."""
    pending: dict[tuple[str, str, Any], int] = {}
    kept = []
    for edge in edges:
        reverse = _edge_key(edge, reverse=True)
        if pending.get(reverse):
            pending[reverse] -= 1
            continue
        pending[_edge_key(edge)] = pending.get(_edge_key(edge), 0) + 1
        kept.append(edge)
    return kept


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


GENERIC_ARRAY_PROFILES =("Comparison-based array algorithm", "Array iteration")
DP_LIKE_NAMES = frozenset({"dp", "memo", "can", "ways", "f", "best", "reach", "reachable", "possible", "ok"})
_SUBSCRIPT_WRITE = re.compile(
    r"\b([A-Za-z_]\w*)\s*(?:\[(?:[^\[\]]|\[[^\[\]]*\])*\]\s*)+"
    r"(?:(?:[-+*/%^|&]|//|<<|>>|\*\*)?=(?!=)|\+\+|--)"
)


_POINTER_SUBSCRIPT = re.compile(
    r"\b([A-Za-z_]\w*)\s*\[\s*(l|r|lo|hi|low|high|left|right|mid)\s*\]", re.IGNORECASE
)
# `l = i + 1` (or Python's `l, r = i + 1, n - 1`): the left pointer starts after an outer
# scan's index, as in three-sum.
_INNER_POINTER_START = re.compile(
    r"\b(?:l|lo|low|left|j)\s*(?:,\s*\w+\s*)?=\s*(?:i|idx)\s*\+\s*1\b", re.IGNORECASE
)


_SUBSCRIPT = re.compile(r"\b([A-Za-z_]\w*)\s*\[\s*([A-Za-z_]\w*)\s*(?=[\]+\-*/%])")


def _subscripts(source: str) -> frozenset[tuple[str, str]]:
    """`(a, i)` for each `a[i]`, `a[i+1]`, `pairs[l][0]` in the source."""
    return frozenset((match.group(1), match.group(2)) for match in _SUBSCRIPT.finditer(source))


def _pointer_targets(source: str) -> tuple[str, ...]:
    """Containers the search pointers index (`pairs[l]`, `a[mid]`), most indexed first."""
    counts: dict[str, int] = {}
    for match in _POINTER_SUBSCRIPT.finditer(source):
        counts[match.group(1)] = counts.get(match.group(1), 0) + 1
    return tuple(sorted(counts, key=lambda name: -counts[name]))


def _with_pointers(profile: AlgorithmProfile, source: str) -> AlgorithmProfile:
    """Draw the container the pointers really index, and tell two-sum from three-sum.

    Two Sum sorts a copy (`pairs`) and walks `l`/`r` over it; drawing the input `a` with
    those markers pointed at the wrong numbers.
    """
    if profile.kind not in {"three_sum", "binary_search", "sorting"}:
        return profile
    targets = _pointer_targets(source)
    if not targets:
        return profile
    lower = re.search(r"\b(?:l|lo|low|left)\b", source, re.IGNORECASE)
    upper = re.search(r"\b(?:r|hi|high|right)\b", source, re.IGNORECASE)
    if profile.kind == "binary_search" or not (lower and upper):
        return replace(profile, focus=targets)
    if _INNER_POINTER_START.search(source):
        return replace(profile, kind="three_sum", name="Three-sum · sort + two pointers", focus=targets)
    return AlgorithmProfile(
        "two_pointers",
        "Two pointers · sorted array",
        "array",
        0.9,
        ("sorted sequence", "left/right pointers", "target sum"),
        targets,
    )


def _with_focus(profile: AlgorithmProfile, source: str, language: str) -> AlgorithmProfile:
    """Point a generic array profile at the array its loops write (`dp`, `can`), not the input."""
    pointed = _with_pointers(profile, source)
    if pointed is not profile:
        return pointed
    generic = profile.name in GENERIC_ARRAY_PROFILES
    if not generic and profile.kind != "dynamic_programming":
        return profile
    focus = _loop_written_arrays(source, language)
    if not focus:
        return profile
    if generic and focus[0].lower() in DP_LIKE_NAMES:
        return AlgorithmProfile(
            "dynamic_programming",
            "Dynamic programming · 1D table",
            "array",
            0.8,
            ("1D state array", "updated inside loops"),
            focus,
        )
    return replace(profile, focus=focus)


def _loop_written_arrays(source: str, language: str) -> tuple[str, ...]:
    if language == "cpp":
        from .cpp_source import strip_code

        source = strip_code(source)
    loops = loop_ranges(source, language)
    depth_of: dict[str, int] = {}
    for line_number, line in enumerate(source.split("\n"), start=1):
        if language != "cpp":
            line = line.split("#", 1)[0]
        depth = sum(loop.first_line <= line_number <= loop.last_line for loop in loops)
        if not depth:
            continue
        for match in _SUBSCRIPT_WRITE.finditer(line):
            name = match.group(1)
            depth_of[name] = max(depth_of.get(name, 0), depth)
    return tuple(sorted(depth_of, key=lambda name: -depth_of[name]))


AUTO_VIEW = "auto"
# Lists of pairs under these names record visits, and these tables hold values, not edges.
NOT_A_GRAPH_NAMES = frozenset({
    "vis", "visited", "seen", "used", "done",
    "dp", "memo", "dist", "dis", "d", "cnt", "cost", "pre", "pref", "prefix", "ps", "sum", "sums",
    "up", "anc", "lift", "jump", "sp",
})
# Arrays that record which cells/vertices a search has reached.
VISITED_LIKE_NAMES = frozenset(
    {"vis", "visited", "seen", "par", "parent", "back", "mov", "move", "moves", "from", "pre", "prev", "dist", "dis"}
)
# Same-shaped grids that mark a cell as reached when they hold anything for it.
REACHED_GRID_NAMES = ("mov", "move", "moves", "back", "from", "pre", "prev", "par", "parent", "dist", "dis", "d", "step", "steps")
FRONTIER_NAMES = frozenset({"q", "queue", "que", "pq", "st", "stack", "frontier", "dq"})
MAX_VIEW_VARIABLES = 6
_VARIABLE_RENDERERS = ("grid", "array", "cells", "graph")


def _view_catalog(scopes: list[dict[str, Any]], steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """List every (renderer, variable) pair whose data shape appears somewhere in the trace."""
    found: dict[str, list[str]] = {renderer: [] for renderer in _VARIABLE_RENDERERS}

    def add(renderer: str, name: str) -> None:
        if name not in found[renderer]:
            found[renderer].append(name)

    for scope in scopes:
        for name, value in scope.items():
            if name.startswith("__"):
                continue
            if _is_grid(value):
                add("grid", name)
            # Any list can be shown as a row of cells; rows of a grid show as compact lists.
            # A string shows one character per cell.
            if (isinstance(value, list) and value) or (isinstance(value, str) and len(value) >= 2):
                add("cells", name)
            if _numeric_array_projection(value) is not None:
                add("array", name)
            if _is_adjacency(value, name):
                add("graph", name)

    catalog = [
        {"id": f"{renderer}:{name}", "renderer": renderer, "variable": name}
        for renderer in _VARIABLE_RENDERERS
        for name in found[renderer][:MAX_VIEW_VARIABLES]
    ]
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
        return _grid_visualization(scope, step, name, extents)
    if renderer == "array":
        return _array_visualization(scope, profile, name, extents)
    if renderer == "cells":
        return _cells_visualization(scope, profile, name, language, extents)
    if renderer == "graph":
        return _graph_visualization(scope, name)
    if renderer == "dsu":
        return _union_find_visualization(scope, name, view.get("first", 0))
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


def _mark_infinite(model: dict[str, Any], sentinels: dict[str, set[Any]]) -> None:
    """Entries holding an "infinity" placeholder (`INF = 1e9` in a dp or dist array).

    A value counts once it filled two or more entries of that array at some step (`[INF] * n`),
    and only if it is a usual INF constant, so a large input value is never taken for one.
    Bars draw these apart instead of letting 10^9 flatten every real value.
    """
    if model.get("renderer") != "array" or not model.get("ready"):
        return
    values = model.get("values") or []
    known = sentinels.setdefault(str(model.get("name")), set())
    for value in set(values):
        if value not in known and _is_infinity(value) and values.count(value) >= 2:
            known.add(value)
    infinite = [index for index, value in enumerate(values) if value in known or value == float("inf")]
    if infinite:
        model["infinite"] = infinite


def _graph_profile(identifiers: set[str], recursive: str | None) -> AlgorithmProfile:
    if "priority_queue" in identifiers:
        name, kind = "Dijkstra · shortest paths", "dijkstra"
    elif "queue" in identifiers and identifiers & {"indeg", "indegree", "in_degree", "deg"}:
        name, kind = "Topological order · BFS", "topological_sort"
    elif "queue" in identifiers:
        name, kind = "Breadth-first search", "bfs"
    elif recursive:
        name, kind = "Depth-first search · recursive", "dfs"
    else:
        name, kind = "Depth-first search · iterative", "dfs"
    return AlgorithmProfile(
        kind,
        name,
        "graph",
        0.9,
        ("adjacency structure", "visited/parent state", "traversal frontier"),
    )


def _calls_itself(code: str, name: str) -> bool:
    """True when a call to `name` appears inside the body of `name` itself."""
    for definition in re.finditer(rf"\b{re.escape(name)}\s*\([^;{{}}]*\)\s*(?:const\s*)?\{{", code):
        depth = 0
        for position in range(definition.end() - 1, len(code)):
            if code[position] == "{":
                depth += 1
            elif code[position] == "}":
                depth -= 1
                if depth == 0:
                    body = code[definition.end() : position]
                    if re.search(rf"(?<![\w.]){re.escape(name)}\s*\(", body):
                        return True
                    break
    return False


def _classify_cpp(source: str, shapes: set[str]) -> AlgorithmProfile:
    identifiers = {name.lower() for name in re.findall(r"\b[A-Za-z_]\w*\b", source)}
    compact = re.sub(r"//.*?$|/\*.*?\*/", " ", source, flags=re.MULTILINE | re.DOTALL)
    loop_count = len(re.findall(r"\b(?:for|while)\s*\(", compact))
    has_visited = bool(identifiers & VISITED_LIKE_NAMES)
    has_frontier = bool(identifiers & {"stack", "queue", "frontier", "priority_queue", "deque", "pq"})
    has_directions = bool(identifiers & {"dirs", "directions", "dx", "dy", "dc", "dr"})
    function_names = re.findall(
        r"\b(?:int|long|void|bool|double|float|string|auto)\s+([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{",
        compact,
    )
    recursive = next(
        (name for name in function_names if name != "main" and _calls_itself(compact, name)),
        None,
    )

    # Tree and graph code (a real adjacency list plus a traversal) is drawn as a graph even
    # when it also keeps dp/dist arrays or a queue of pairs: the structure is what the
    # student needs to see.
    if "adjacency_list" in shapes and (has_visited or has_frontier or recursive):
        return _graph_profile(identifiers, recursive)

    # A queue plus direction arrays is a grid search even when the distance table (`d`) is
    # the only visited state.
    if ("grid" in shapes or "matrix" in shapes) and (
        (has_visited and (has_frontier or has_directions)) or (has_frontier and has_directions)
    ):
        strategy = "BFS" if "queue" in identifiers else "DFS / stack traversal"
        return AlgorithmProfile(
            "grid_traversal",
            f"Grid traversal · {strategy}",
            "grid",
            0.93,
            ("2D indexed data", "visited state", "directional frontier"),
        )

    if "dp" in identifiers and ("matrix" in shapes or re.search(r"\bdp\s*\[", compact)):
        two_dimensional = re.search(r"\bdp\s*\[[^\]]*\]\s*\[", compact)
        return AlgorithmProfile(
            "dynamic_programming",
            "Dynamic programming table",
            "grid" if two_dimensional else "array",
            0.88,
            ("2D dp state", "nested iteration", "indexed state updates"),
        )

    lower_names = {"low", "left", "lo", "l"} & identifiers
    upper_names = {"high", "right", "hi", "r"} & identifiers
    target_names = {"target", "sum", "x", "k", "goal"} & identifiers
    three_sum_pointers = bool(lower_names and upper_names) or {
        "i", "j", "idx", "need"
    }.issubset(identifiers)
    if (
        "numeric_array" in shapes
        and target_names
        and three_sum_pointers
        and loop_count >= 2
        and re.search(r"\b(?:std::)?sort\s*\(", compact)
    ):
        return AlgorithmProfile(
            "three_sum",
            "Three-sum · sort + two pointers",
            "array",
            0.95,
            ("sorted numeric sequence", "outer scan", "left/right pointers", "target sum"),
        )
    if "mid" in identifiers and lower_names and upper_names and "while" in identifiers:
        return AlgorithmProfile(
            "binary_search",
            "Binary search",
            "array",
            0.92,
            ("low/high bounds", "mid index", "while loop"),
        )

    if "graph" in shapes and has_visited:
        return _graph_profile(identifiers, recursive)

    if re.search(r"\b(?:std::)?sort\s*\(", compact):
        return AlgorithmProfile(
            "sorting",
            "Array sorting",
            "array",
            0.88,
            ("sorting operation", "sequence state"),
        )

    # A 2D table (an equation system, a matrix power) is drawn as a grid, not as its first column;
    # memoised recursion keeps its call tree.
    if "wide_matrix" in shapes and not recursive:
        return AlgorithmProfile(
            "matrix_processing",
            "Matrix processing",
            "grid",
            0.7,
            ("2D state", "indexed matrix access"),
        )

    indexed_writes = len(re.findall(r"\b[A-Za-z_]\w*\s*\[[^\]]+\]\s*=", compact))
    if "numeric_array" in shapes and loop_count >= 2 and indexed_writes:
        return AlgorithmProfile(
            "sorting",
            "Comparison-based array algorithm",
            "array",
            0.78,
            ("nested loops", "indexed array updates"),
        )

    if recursive:
        return AlgorithmProfile(
            "recursion",
            f"Recursive algorithm · {recursive}()",
            "call_tree",
            0.88,
            ("self-recursive function call", "growing call stack"),
        )

    if "matrix" in shapes:
        return AlgorithmProfile(
            "matrix_processing",
            "Matrix processing",
            "grid",
            0.7,
            ("2D state", "indexed matrix access"),
        )

    if "numeric_array" in shapes and loop_count:
        return AlgorithmProfile(
            "array_processing",
            "Array iteration",
            "array",
            0.68,
            ("numeric sequence", "iterative processing"),
        )

    return AlgorithmProfile(
        "generic",
        "General C++ execution",
        "execution",
        0.45,
        ("No specialized pattern matched",),
    )


def _classify(features: _FeatureVisitor, shapes: set[str]) -> AlgorithmProfile:
    names = features.names
    methods = features.method_calls
    has_visited = bool(names & VISITED_LIKE_NAMES)
    has_frontier = bool(names & {"stack", "queue", "frontier", "deque"})
    has_directions = bool(names & {"dirs", "directions", "dx", "dy"})

    if (
        "grid" in shapes
        and features.max_subscript_depth >= 2
        and has_visited
        and (has_frontier or has_directions)
    ):
        strategy = "BFS" if "popleft" in methods else "DFS / stack traversal"
        return AlgorithmProfile(
            "grid_traversal",
            f"Grid traversal · {strategy}",
            "grid",
            0.96,
            ("2D indexed data", "visited matrix", "directional frontier"),
        )

    if "dp" in names and "matrix" in shapes and features.max_loop_depth >= 2:
        return AlgorithmProfile(
            "dynamic_programming",
            "Dynamic programming table",
            "grid",
            0.9,
            ("2D dp state", "nested iteration", "indexed state updates"),
        )

    lower_names = {"low", "left", "lo", "l"} & names
    upper_names = {"high", "right", "hi", "r"} & names
    target_names = {"target", "sum", "x", "k", "goal"} & names
    three_sum_pointers = bool(lower_names and upper_names) or {
        "i", "j", "idx", "need"
    }.issubset(names)
    if (
        "numeric_array" in shapes
        and target_names
        and three_sum_pointers
        and features.max_loop_depth >= 2
        and ("sort" in methods or "sorted" in features.direct_calls)
    ):
        return AlgorithmProfile(
            "three_sum",
            "Three-sum · sort + two pointers",
            "array",
            0.95,
            ("sorted numeric sequence", "outer scan", "left/right pointers", "target sum"),
        )
    if "mid" in names and lower_names and upper_names and features.while_count:
        return AlgorithmProfile(
            "binary_search",
            "Binary search",
            "array",
            0.93,
            ("low/high bounds", "mid index", "while loop"),
        )

    if "graph" in shapes and has_visited:
        if "popleft" in methods:
            name, kind = "Breadth-first search", "bfs"
        elif features.recursive_functions:
            name, kind = "Depth-first search · recursive", "dfs"
        else:
            name, kind = "Depth-first search · iterative", "dfs"
        return AlgorithmProfile(
            kind,
            name,
            "graph",
            0.9,
            ("adjacency structure", "visited/parent state", "traversal frontier"),
        )

    if "sort" in methods or "sorted" in features.direct_calls:
        return AlgorithmProfile(
            "sorting",
            "Array sorting",
            "array",
            0.88,
            ("sorting operation", "sequence state"),
        )

    if (
        "numeric_array" in shapes
        and features.max_loop_depth >= 2
        and features.subscript_writes
    ):
        return AlgorithmProfile(
            "sorting",
            "Comparison-based array algorithm",
            "array",
            0.76,
            ("nested loops", "indexed array updates"),
        )

    if features.recursive_functions:
        function_name = sorted(features.recursive_functions)[0]
        return AlgorithmProfile(
            "recursion",
            f"Recursive algorithm · {function_name}()",
            "call_tree",
            0.9,
            ("self-recursive function call", "growing call stack"),
        )

    if "matrix" in shapes and features.max_subscript_depth >= 2:
        return AlgorithmProfile(
            "matrix_processing",
            "Matrix processing",
            "grid",
            0.7,
            ("2D state", "indexed matrix access"),
        )

    if "numeric_array" in shapes and features.max_loop_depth:
        return AlgorithmProfile(
            "array_processing",
            "Array iteration",
            "array",
            0.66,
            ("numeric sequence", "iterative processing"),
        )

    return AlgorithmProfile(
        "generic",
        "General Python execution",
        "execution",
        0.45,
        ("No specialized pattern matched",),
    )


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
            if _is_grid(value) and name.lower() not in FRONTIER_NAMES:
                shapes.add("matrix")
                # Rows of two are usually (value, index) pairs, which read best as bars.
                if all(len(row) >= 3 for row in _used_rows(value)):
                    shapes.add("wide_matrix")
                if name.lower() not in {"vis", "visited", "seen", "dp"}:
                    shapes.add("grid")
            if _numeric_array_projection(value) is not None:
                shapes.add("numeric_array")
            if _is_adjacency(value, name) and name.lower() not in NOT_A_GRAPH_NAMES and name not in edge_id_lists:
                shapes.add("graph")
                # Rows of different lengths: a real adjacency list, not a numeric table.
                if isinstance(value, list) and len({len(row) for row in value}) > 1:
                    shapes.add("adjacency_list")
        if shapes >= {"matrix", "wide_matrix", "grid", "numeric_array", "graph", "adjacency_list"}:
            break
    return shapes


def _decode_scope(step: dict[str, Any], decoded: dict[int, Any] | None = None) -> dict[str, Any]:
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


class _SetItems(list):
    """Decoded members of a set: a list for every view, but never a table of rows."""

    # `usage._changed_cells` marks new members, not positions, of an unordered container.
    unordered = True


class _PartialItems(list):
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
            for item in value.get("items", [])[:MAX_VISUAL_ITEMS]
        ]
        unordered = type_name in {"set", "frozenset"} or value.get("class_name") in SET_CLASSES
        if unordered:
            return _SetItems(items)
        if value.get("truncated") and not value.get("fill"):
            # Only the first entries were read; the rest are unknown (not zero).
            return _PartialItems(items, value.get("length"))
        return items
    if type_name == "dict":
        decoded: dict[Any, Any] = {}
        for entry in value.get("entries", [])[:MAX_VISUAL_ITEMS]:
            key = _decode_value(entry.get("key"), registry, seen)
            item = _decode_value(entry.get("value"), registry, seen)
            try:
                decoded[key] = item
            except TypeError:
                decoded[str(key)] = item
        return decoded
    return None


def _visualization_for(
    profile: AlgorithmProfile,
    scope: dict[str, Any],
    step: dict[str, Any],
    extents: dict[str, tuple[int, int]] | None = None,
) -> dict[str, Any]:
    if profile.renderer == "grid":
        return _grid_visualization(scope, step, None, extents)
    if profile.renderer == "array":
        return _array_visualization(scope, profile, None, extents)
    if profile.renderer == "graph":
        return _graph_visualization(scope)
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


def _named_values(
    scope: dict[str, Any],
    name: str | None,
    preferred_names: Iterable[str],
) -> Iterable[tuple[str, Any]]:
    """Candidates for a view: the chosen variable only, or every variable by preference."""
    if name is None:
        return _preferred_values(scope, preferred_names)
    return [(name, scope[name])] if name in scope else []


def _grid_visualization(
    scope: dict[str, Any],
    step: dict[str, Any],
    name: str | None = None,
    extents: dict[str, tuple[int, int]] | None = None,
) -> dict[str, Any]:
    if name is None:
        # A character map (the maze, the board) is the grid; tables beside it only mark it.
        grid_name, grid = _character_map(scope)
        if grid is None:
            grid_name, grid = _find_grid(scope)
    else:
        value = scope.get(name)
        grid_name, grid = (name, value) if _is_grid(value) else (None, None)
    if grid is None:
        return {"renderer": "grid", "ready": False}
    rows = _normalize_grid(_used_rows(grid))
    names = [grid_name]
    walls = _wall_cells(rows)
    # A character map (`a`) and a number table (`dp`) are drawn as one grid: the map
    # while the table is still all zero (the input is being read), then the table's
    # numbers with the map's walls kept in place.
    pair = _map_and_table(scope) if name is None else None
    if pair is not None:
        (map_name, map_rows), (table_name, table_rows) = pair
        walls = _wall_cells(map_rows)
        filled = any(_has_content(cell) for row in table_rows for cell in row)
        height = max(len(map_rows), len(table_rows))
        width = max((len(row) for row in [*map_rows, *table_rows]), default=0)
        rows = [
            [
                _cell(map_rows, row, column, "\0")
                if (row, column) in walls or not filled
                else _cell(table_rows, row, column, 0)
                for column in range(width)
            ]
            for row in range(height)
        ]
        grid_name = table_name if filled else map_name
        names = [table_name, map_name]
    # The largest part used anywhere in the trace keeps the grid one size from start to end,
    # including while the input is still being read into it.
    used = [(extents or {}).get(variable, (0, 0)) for variable in names]
    blank = "\0" if any(isinstance(cell, str) for row in rows for cell in row) or not rows else 0
    target_height = max([len(rows), *(height for height, _ in used)])
    target_width = max([max((len(row) for row in rows), default=0), *(width for _, width in used)])
    rows = [
        list(row) + [blank] * (target_width - len(row))
        for row in rows + [[] for _ in range(target_height - len(rows))]
    ]
    full_height = len(rows)
    full_width = max((len(row) for row in rows), default=0)
    row_count = _visible_extent(
        full_height,
        [index for index, row in enumerate(rows) if any(_has_content(cell) for cell in row)]
        + [height - 1 for height, _ in used if height],
        scope.get("n"),
        MAX_VISUAL_ROWS,
    )
    column_count = _visible_extent(
        full_width,
        [index for row in rows for index, cell in enumerate(row) if _has_content(cell)]
        + [width - 1 for _, width in used if width],
        scope.get("m", scope.get("n")),
        MAX_VISUAL_COLUMNS,
    )
    if not row_count or not column_count:
        return {"renderer": "grid", "ready": False}
    rows = [row[:column_count] for row in rows[:row_count]]

    visited_name, visited = _find_visited(scope, row_count, column_count)
    # A wall is never visited, whatever value a table keeps for it.
    for row, column in walls:
        if row < row_count and column < column_count:
            visited[row][column] = False
    active, active_names, coordinates = _active_cells(scope, row_count, column_count)
    frontier_name, frontier = _frontier_cells(scope, row_count, column_count)
    queue = scope.get(frontier_name) if frontier_name else None
    return {
        "renderer": "grid",
        "ready": True,
        "name": grid_name,
        "uses": _unique_names([*names, visited_name, *active_names, frontier_name]),
        "rows": rows,
        "walls": [
            {"row": row, "column": column}
            for row, column in sorted(walls)
            if row < row_count and column < column_count
        ],
        "visited": visited,
        "active": active,
        "frontier": frontier,
        # Coordinates as numbers and the queue in its order: the coloured cells alone show
        # neither which variable holds a cell nor which cell leaves the queue next.
        "coordinates": coordinates,
        "queue": (
            {"name": frontier_name, "entries": [f"({item[0]}, {item[1]})" for item in queue[:MAX_VISUAL_ITEMS]]}
            if isinstance(queue, list)
            else None
        ),
        "truncated": full_height > MAX_VISUAL_ROWS or full_width > MAX_VISUAL_COLUMNS,
        "event": step.get("event"),
    }


WALL_CHARACTERS = frozenset("#*")


def _grid_extents(scopes: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    """Rows and columns holding data in each 2D array (and the used length of each 1D
    array, as `(length, 0)`) over the whole trace."""
    extents: dict[str, tuple[int, int]] = {}
    measured: dict[int, tuple[int, int]] = {}
    for scope in scopes:
        for name, value in scope.items():
            if not isinstance(value, list) or not value:
                continue
            if not all(isinstance(row, (list, str)) for row in value):
                if id(value) not in measured:
                    used = max((index for index, item in enumerate(value) if _has_content(item)), default=-1) + 1
                    measured[id(value)] = (used, 0)
                previous = extents.get(name, (0, 0))
                extents[name] = (max(previous[0], measured[id(value)][0]), 0)
                continue
            if id(value) not in measured:
                rows = _normalize_grid(_used_rows(value))
                content = [
                    (row_index, column_index)
                    for row_index, row in enumerate(rows)
                    for column_index, cell in enumerate(row)
                    if _has_content(cell)
                ]
                measured[id(value)] = (
                    max((row for row, _ in content), default=-1) + 1,
                    max((column for _, column in content), default=-1) + 1,
                )
            height, width = measured[id(value)]
            previous = extents.get(name, (0, 0))
            extents[name] = (max(previous[0], height), max(previous[1], width))
    return extents


def _character_map(scope: dict[str, Any]) -> tuple[str | None, list[Any] | None]:
    """The first character grid that is not a search's bookkeeping (`mov`, `vis`)."""
    skip = {"vis", "visited", "seen", *REACHED_GRID_NAMES}
    for name, value in _preferred_values(scope, ("grid", "board", "maze", "matrix", "map", "mp", "a", "s", "g")):
        if name.lower() in skip or not isinstance(value, list) or not value:
            continue
        if not all(isinstance(row, str) for row in value):
            continue
        # Before the input is read a C++ char grid is all empty rows; it is still the map.
        if _is_grid(value) or all(row == "" for row in value):
            return name, value
    return None, None


def _map_and_table(
    scope: dict[str, Any],
) -> tuple[tuple[str, list[list[Any]]], tuple[str, list[list[Any]]]] | None:
    """A character grid plus a numeric grid, as in grid DP (`a` and `dp`)."""
    character_grid = number_grid = None
    for name, value in _preferred_values(scope, ("grid", "board", "maze", "matrix", "a", "dp")):
        if name.lower() in {"vis", "visited", "seen"}:
            continue
        # A C++ char grid before any input is read: every row is still an empty string.
        if (
            character_grid is None
            and isinstance(value, list)
            and value
            and all(row == "" for row in value)
        ):
            character_grid = (name, [])
            continue
        if not _is_grid(value):
            continue
        rows = _normalize_grid(_used_rows(value))
        cells = [cell for row in rows for cell in row]
        if character_grid is None and all(isinstance(cell, str) and len(cell) <= 1 for cell in cells):
            character_grid = (name, rows)
        elif number_grid is None and all(_is_number(cell) for cell in cells):
            number_grid = (name, rows)
    if character_grid is None or number_grid is None:
        return None
    # The table must cover the map, which rules out small tables such as `dirs`.
    map_rows, table_rows = character_grid[1], number_grid[1]
    if len(table_rows) < len(map_rows) or max(map(len, table_rows), default=0) < max(map(len, map_rows), default=0):
        return None
    return character_grid, number_grid


def _wall_cells(rows: list[list[Any]]) -> set[tuple[int, int]]:
    return {
        (row_index, column_index)
        for row_index, row in enumerate(rows)
        for column_index, cell in enumerate(row)
        if isinstance(cell, str) and cell in WALL_CHARACTERS
    }


def _cell(rows: list[list[Any]], row: int, column: int, blank: Any) -> Any:
    if row < len(rows) and column < len(rows[row]):
        return rows[row][column]
    return blank


def _has_content(cell: Any) -> bool:
    if isinstance(cell, list):
        return any(_has_content(item) for item in cell)
    return cell not in (0, "", "\0", None) and cell is not False


def _visible_extent(size: int, content: list[int], count: Any, cap: int) -> int:
    """How much of a grid dimension to draw.

    A dimension that reaches the visual cap is a fixed-size C++ array (`dp[1005][1005]`);
    it is cut to the cells that hold data, and at least to `n` once `n` is read.
    Smaller grids are the program's own size and are drawn whole.
    """
    if size < cap:
        return size
    used = max(content) + 1 if content else 0
    if _is_index(count) and 0 < count <= size:
        used = max(used, count)
    return min(size, used)


LOWER_BOUND_NAMES = ("lo", "low", "left", "l")
UPPER_BOUND_NAMES = ("hi", "high", "right", "r")
TARGET_NAMES = ("target", "x", "k", "goal", "key")
SUM_NAMES = ("sum", "s", "cur", "total", "need")


ARRAY_NAMES = ("arr", "a", "nums", "values", "inf", "data")


def _array_visualization(
    scope: dict[str, Any],
    profile: AlgorithmProfile,
    name: str | None = None,
    extents: dict[str, tuple[int, int]] | None = None,
) -> dict[str, Any]:
    preferred = ("dp", *profile.focus, *ARRAY_NAMES) if profile.kind == "dynamic_programming" else (*profile.focus, *ARRAY_NAMES)
    candidates = _named_values(scope, name, preferred)
    if name is None and profile.focus:
        # Before the written array exists (input being read), draw nothing rather than the input.
        focus = {*profile.focus, *(("dp",) if profile.kind == "dynamic_programming" else ())}
        candidates = [(array_name, value) for array_name, value in candidates if array_name in focus]
    for array_name, value in candidates:
        projection = _numeric_array_projection(value)
        if projection is None and array_name in profile.focus and _is_bool_list(value):
            # `can[s] = True`: a reachability table, drawn as 0/1 bars.
            projection = [int(item) for item in value], None
        if projection is None:
            continue
        numeric_values, item_labels = projection
        partial = isinstance(value, _PartialItems)
        # A partly read list is not cut at its last nonzero entry: what follows is unknown.
        length = len(numeric_values) if partial else _logical_length(scope, numeric_values, (extents or {}).get(array_name, (0, 0))[0])
        values = numeric_values[:length][:MAX_VISUAL_ITEMS]
        visualization: dict[str, Any] = {
            "renderer": "array",
            "ready": True,
            "name": array_name,
            "values": values,
            **({"labels": item_labels[: len(values)]} if item_labels is not None else {}),
            "truncated": partial or length > len(values),
        }
        _mark_partial(visualization, value)
        _annotate_indexes(visualization, scope, profile, array_name)
        return visualization
    return {"renderer": "array", "ready": False}


def _mark_partial(visualization: dict[str, Any], value: Any) -> None:
    """Record the real size of a list only partly read (`a` has 80 entries, 50 were read)."""
    if isinstance(value, _PartialItems) and value.total is not None:
        visualization["length"] = value.total


def _cells_visualization(
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
    elif isinstance(value, list):
        partial = isinstance(value, _PartialItems)
        length = len(value) if partial else _logical_length(scope, value, (extents or {}).get(name, (0, 0))[0])
        items = value[:length][:MAX_VISUAL_ITEMS]
    else:
        return {"renderer": "cells", "ready": False}
    visualization: dict[str, Any] = {
        "renderer": "cells",
        "ready": True,
        "name": name,
        "values": [_display_value(item, language) for item in items],
        "truncated": isinstance(value, _PartialItems) or length > len(items),
    }
    _mark_partial(visualization, value)
    _annotate_indexes(visualization, scope, profile, name)
    return visualization


def _logical_length(scope: dict[str, Any], values: list[Any], extent: int = 0) -> int:
    """How much of an array to draw.

    Fixed-size C++ arrays (`dp[1000005]`, read up to the item limit) are cut to the part
    used anywhere in the trace (`extent`), so the view keeps one size, and at least to `n`.
    Entries past `n` that hold data stay visible (`dp[n]`, 1-indexed `p[n]`).
    """
    count = scope.get("n")
    has_count = _is_index(count) and 0 < count <= len(values)
    capped = len(values) >= MAX_ITEMS and extent > 0
    if not has_count and not capped:
        return len(values)
    floor = max(count if has_count else 0, extent if capped else 0)
    used = len(values)
    while used > floor and not values[used - 1]:
        used -= 1
    return used


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
        label, index = _scope_lookup(scope, variable)
        # A variable the code uses as an index of other containers only marks those.
        if label in indexes and (name, label) not in profile.subscripts:
            continue
        if _is_index(index) and 0 <= index < length:
            markers.append({"index": index, "role": role, "label": label})
        elif _is_index(index) and length <= index < visualization.get("length", length):
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
                label, reading = _scope_lookup(scope, candidate)
                if _is_number(reading):
                    readouts.append({"label": label, "value": reading})
                    break
        if readouts:
            visualization["readouts"] = readouts
            uses.extend(readout["label"] for readout in readouts)
    visualization["uses"] = _unique_names(uses)


def _display_value(value: Any, language: str, depth: int = 0) -> str:
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
        shown = ", ".join(_display_value(item, language, depth + 1) for item in value[:4])
        return f"[{shown}{', …' if len(value) > 4 else ''}]"
    if isinstance(value, dict):
        return "{…}"
    return str(value)


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
        label, value = _scope_lookup(scope, name)
        if _is_index(value):
            return label, value
    return None, None


def _unique_names(names: Iterable[str | None]) -> list[str]:
    """Variable names a visualization draws, so the Variables panel can skip them."""
    return list(dict.fromkeys(name for name in names if name))


def _scope_lookup(scope: dict[str, Any], name: str) -> tuple[str, Any]:
    if name in scope:
        return name, scope[name]
    for key, value in scope.items():
        if key.lower() == name:
            return key, value
    return name, None


def _is_index(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _graph_visualization(scope: dict[str, Any], graph_name: str | None = None) -> dict[str, Any]:
    for name, value in _named_values(scope, graph_name, ("graph", "g", "adj", "adjacency")):
        if not _is_adjacency(value, name) or (graph_name is None and name.lower() in NOT_A_GRAPH_NAMES):
            continue
        adjacency = _adjacency_rows(value) or []
        if isinstance(value, dict):
            node_values = {source for source, _ in adjacency}
        else:
            node_values = {source for source, targets in adjacency if targets}
            # Fixed-size C++ adjacency arrays have many unused rows; only keep
            # isolated vertices inside the logical 0..n-1 or 1..n range.
            count = scope.get("n")
            if _is_index(count) and 0 < count < len(value):
                first = 1 if not value[0] else 0
                node_values.update(range(first, first + count))
        edges: list[dict[str, str]] = []
        for source, targets in adjacency:
            for target, weight in targets:
                node_values.add(target)
                edge = {"source": str(source), "target": str(target)}
                if weight is not None:
                    edge["weight"] = _display_value(weight, "cpp")
                edges.append(edge)
        visited_name, visited_value = next(
            (
                (key, scope[key])
                for key in ("visited", "vis", "seen", "par", "parent")
                if key in scope
            ),
            (None, []),
        )
        numeric_nodes = [node for node in node_values if _is_index(node)]
        if isinstance(visited_value, list) and visited_name in {"par", "parent"}:
            visited = [
                str(index)
                for index, item in enumerate(visited_value)
                if item not in (0, False)
            ]
        elif isinstance(visited_value, list) and _is_flag_array(visited_value, numeric_nodes):
            visited = [str(index) for index, item in enumerate(visited_value) if item]
        elif isinstance(visited_value, list):
            visited = [str(item) for item in visited_value]
        else:
            visited = []
        if visited_name is None:
            visited_name, visited = _reached_vertices(scope, numeric_nodes)
            visited_value = scope.get(visited_name) if visited_name else []
        current_name = next(
            (
                key
                for key in ("u", "node", "current", "vertex", "now", "cur")
                if isinstance(scope.get(key), (str, int, float)) and not isinstance(scope.get(key), bool)
            ),
            None,
        )
        current = None if current_name is None else str(scope[current_name])
        node_ids = {str(node) for node in node_values}
        checking = _checking_edge(scope, edges, current_name)
        if checking is not None and current_name is None:
            current_name, current = checking["from_name"], checking["source"]
        frontier_name, frontier, frontier_entries = _graph_frontier(scope, node_ids)
        label_name, labels = _graph_labels(scope, numeric_nodes, {name} if visited_name in GRAPH_LABEL_NAMES else {name, visited_name})
        parents = _tree_parents(node_values, edges)
        route_name, route = _graph_route(scope, node_ids, edges, current)
        return {
            "renderer": "graph",
            "ready": True,
            "name": name,
            "uses": _unique_names([
                name,
                visited_name if isinstance(visited_value, list) else None,
                current_name,
                checking["to_name"] if checking else None,
                frontier_name,
                route_name,
            ]),
            # The edge from the current vertex to the neighbour it is looking at.
            "checking": {"source": checking["source"], "target": checking["target"]} if checking else None,
            "nodes": sorted(str(node) for node in node_values),
            "edges": edges[:100],
            "visited": visited,
            "current": current,
            "frontier": (
                {"name": frontier_name, "items": frontier, **({"entries": frontier_entries} if frontier_entries else {})}
                if frontier_name
                else None
            ),
            "labels": {"name": label_name, "values": labels} if label_name else None,
            # The path a backtracking loop has built so far (`route`), in order.
            "route": route,
            # A tree is laid out from its root down instead of around a circle.
            "layout": "tree" if parents else None,
            "parents": parents,
        }
    return {"renderer": "graph", "ready": False}


ROUTE_NAMES = ("route", "path", "ans", "answer", "res", "result", "trace", "way", "walk", "order")


def _graph_route(
    scope: dict[str, Any],
    node_ids: set[str],
    edges: list[dict[str, str]],
    current: str | None,
) -> tuple[str | None, dict[str, Any] | None]:
    """A list of vertices the code builds as an answer path (CSES 1667 walks back from n by
    `dis`, pushing each vertex): drawn as a highlighted path. While it is being built, the
    vertex the walk has moved to (`now`) continues the path when an edge joins them."""
    joined = {(edge["source"], edge["target"]) for edge in edges}
    for name in ROUTE_NAMES:
        key, value = _scope_lookup(scope, name)
        if not isinstance(value, list) or not value:
            continue
        items = [str(item) for item in value if _is_index(item)]
        if len(items) != len(value) or not all(item in node_ids for item in items):
            continue
        last = items[-1]
        extends = current is not None and current != last and ((last, current) in joined or (current, last) in joined)
        return key, {"name": key, "items": items, **({"next": current} if extends else {})}
    return None, None


REACHED_VERTEX_NAMES = ("team", "color", "colour", "side", "dist", "dis", "depth", "level", "comp")


def _reached_vertices(scope: dict[str, Any], numeric_nodes: list[int]) -> tuple[str | None, list[str]]:
    """Vertices a search has reached, read from a per-vertex state array: anything but
    0/-1/false, and not an 'infinity' placeholder."""
    for name in REACHED_VERTEX_NAMES:
        key, value = _scope_lookup(scope, name)
        if not isinstance(value, list) or not numeric_nodes:
            continue
        reached = [
            str(node)
            for node in numeric_nodes
            if 0 <= node < len(value)
            and _is_number(value[node])
            and value[node] not in (0, -1)
            and abs(value[node]) < 10**9
        ]
        return key, reached
    return None, []


def _tree_parents(node_values: set[Any], edges: list[dict[str, str]]) -> dict[str, str] | None:
    """Parent of every vertex when the graph is a tree rooted at its smallest vertex."""
    nodes = sorted(str(node) for node in node_values)
    pairs = {tuple(sorted((edge["source"], edge["target"]))) for edge in edges if edge["source"] != edge["target"]}
    if len(nodes) < 2 or len(pairs) != len(nodes) - 1:
        return None
    neighbours: dict[str, list[str]] = {node: [] for node in nodes}
    for first, second in pairs:
        if first not in neighbours or second not in neighbours:
            return None
        neighbours[first].append(second)
        neighbours[second].append(first)
    root = min(nodes, key=lambda node: (not node.isdigit(), int(node) if node.isdigit() else 0, node))
    parents: dict[str, str] = {}
    seen = {root}
    queue = [root]
    for node in queue:
        for child in sorted(neighbours[node], key=lambda value: (len(value), value)):
            if child not in seen:
                seen.add(child)
                parents[child] = node
                queue.append(child)
    return parents if len(seen) == len(nodes) else None


CURRENT_VERTEX_NAMES = ("u", "node", "current", "vertex", "cur", "now", "x", "s", "from")
NEIGHBOUR_NAMES = ("v", "next", "nxt", "to", "nb", "neighbor", "neighbour", "child", "y", "w", "nx", "prev", "pre", "p")


def _checking_edge(
    scope: dict[str, Any],
    edges: list[dict[str, str]],
    current_name: str | None,
) -> dict[str, str] | None:
    """The edge a traversal is looking at: the current vertex and a neighbour variable
    that an edge of the graph really joins (two unrelated integers never qualify)."""
    joined = {(edge["source"], edge["target"]) for edge in edges}
    sources = [current_name] if current_name else list(CURRENT_VERTEX_NAMES)
    for source_name in sources:
        source = scope.get(source_name)
        if not _is_index(source):
            continue
        for target_name in NEIGHBOUR_NAMES:
            target = scope.get(target_name)
            if target_name == source_name or not _is_index(target):
                continue
            if (str(source), str(target)) in joined or (str(target), str(source)) in joined:
                return {"from_name": source_name, "to_name": target_name, "source": str(source), "target": str(target)}
    return None


GRAPH_FRONTIER_NAMES = ("q", "queue", "que", "frontier", "st", "stack", "pq")
# Per-node arrays worth printing beside each vertex, most useful first.
GRAPH_LABEL_NAMES = (
    "dis", "dist", "distance", "d", "depth", "level", "color", "colour", "team",
    "comp", "component", "sub", "subtree", "sz", "size", "cnt",
    "par", "parent", "p", "prev", "pre", "from",
)


def _graph_frontier(scope: dict[str, Any], node_ids: set[str]) -> tuple[str | None, list[str], list[str] | None]:
    """The BFS queue or DFS stack: a list whose entries are all vertices of the graph.

    Dijkstra's priority queue holds (distance, vertex) pairs; the vertex is the second item
    (or the first, when only that one is always a vertex).
    """
    for name in GRAPH_FRONTIER_NAMES:
        key, value = _scope_lookup(scope, name)
        if not isinstance(value, list):
            continue
        if all(isinstance(item, (int, str)) and str(item) in node_ids for item in value):
            return key, [str(item) for item in value[:MAX_VISUAL_ITEMS]], None
        if value and all(isinstance(item, list) and len(item) == 2 for item in value):
            for position in (1, 0):
                if all(isinstance(item[position], (int, str)) and str(item[position]) in node_ids for item in value):
                    # The queue line keeps whole entries, `(6, 2)`: the distance it was pushed
                    # with can be stale, which `dist[v]` beside the vertex does not show.
                    entries = [f"({item[0]}, {item[1]})" for item in value[:MAX_VISUAL_ITEMS]]
                    return key, [str(item[position]) for item in value[:MAX_VISUAL_ITEMS]], entries
    return None, [], None


def _graph_labels(
    scope: dict[str, Any],
    numeric_nodes: list[int],
    taken: set[str | None],
    names: Iterable[str] = GRAPH_LABEL_NAMES,
) -> tuple[str | None, dict[str, Any]]:
    """Values of a per-vertex array such as `dis[v]`, keyed by vertex."""
    if not numeric_nodes:
        return None, {}
    for name in names:
        key, value = _scope_lookup(scope, name)
        if key in taken or not isinstance(value, list):
            continue
        if not all(isinstance(item, (int, float, str)) for item in value):
            continue
        # Fixed-size C++ arrays only carry their first entries; skip vertices past them.
        labels = {str(node): value[node] for node in numeric_nodes if 0 <= node < len(value)}
        if labels:
            return key, labels
    return None, {}


PARENT_NAMES = ("p", "par", "parent", "fa", "f", "link", "root", "boss", "leader", "dsu")
SIZE_NAMES = ("sz", "siz", "size", "rnk", "rank", "cnt", "height")
FIND_NAMES = ("find", "findset", "find_set", "get", "root", "leader", "getroot", "get_root")
MAX_FOREST_NODES = 60


def _union_find_parent(source: str) -> tuple[str | None, int]:
    """Name the parent array of a union-find (a `find`-like function plus `p[i] = i`)
    and the first vertex its initialisation loop sets, so `for (i = 1; ...)` is 1-indexed."""
    code = re.sub(r"//.*?$|/\*.*?\*/|#.*?$", " ", source, flags=re.MULTILINE | re.DOTALL)
    if not re.search(rf"\b(?:{'|'.join(FIND_NAMES)})\s*\(", code, re.IGNORECASE):
        return None, 0
    for name in PARENT_NAMES:
        assignment = re.search(rf"\b{name}\s*\[\s*(\w+)\s*\]\s*=\s*\1\s*[;,)\n]", code)
        if assignment:
            loop = re.findall(
                rf"\bfor\s*\(\s*(?:[\w:]+\s+)*{assignment.group(1)}\s*=\s*(\d+)",
                code[max(0, assignment.start() - 160) : assignment.start()],
            )
            return name, int(loop[-1]) if loop else 0
        # Python: p = list(range(n)) or [i for i in range(n)].
        if re.search(
            rf"\b{name}\s*=\s*(?:list\(\s*)?(?:\[\s*\w+\s+for\s+\w+\s+in\s+)?range\(", code
        ):
            return name, 0
    return None, 0


def _union_find_visualization(
    scope: dict[str, Any],
    name: str | None = None,
    first: int = 0,
) -> dict[str, Any]:
    """Draw a parent array as a forest: an arrow from every vertex to its parent."""
    for key, value in _named_values(scope, name, PARENT_NAMES):
        if not isinstance(value, list) or not all(_is_index(item) for item in value):
            continue
        values = value[: min(_logical_length(scope, value), MAX_FOREST_NODES)]
        # In a 1-indexed array a 0 entry is a slot the initialisation loop has not reached.
        nodes = [
            index
            for index in range(first, len(values))
            if 0 <= values[index] < len(values) and (values[index] != 0 or first == 0)
        ]
        if not any(values[index] == index for index in nodes):
            continue
        node_set = set(nodes)
        current_name = next(
            (
                candidate
                for candidate in ("x", "u", "v", "a", "b", "i")
                if _is_index(scope.get(candidate)) and scope[candidate] in node_set
            ),
            None,
        )
        label_name, labels = _graph_labels(scope, nodes, {key}, SIZE_NAMES)
        return {
            "renderer": "graph",
            "ready": True,
            "name": key,
            "layout": "forest",
            "directed": True,
            "uses": _unique_names([key, current_name, label_name]),
            "nodes": [str(index) for index in nodes],
            "edges": [
                {"source": str(index), "target": str(values[index])}
                for index in nodes
                if values[index] != index and values[index] in node_set
            ],
            "visited": [],
            "current": None if current_name is None else str(scope[current_name]),
            "frontier": None,
            "labels": {"name": label_name, "values": labels} if label_name else None,
        }
    return {"renderer": "graph", "ready": False}


def _find_grid(scope: dict[str, Any]) -> tuple[str | None, list[Any] | None]:
    for name, value in _preferred_values(
        scope,
        ("grid", "board", "maze", "matrix", "dp", "a"),
    ):
        # A queue of (row, col) pairs is the frontier drawn on a grid, not the grid itself.
        if _is_grid(value) and name.lower() not in {"vis", "visited", "seen"} | FRONTIER_NAMES:
            return name, value
    return None, None


def _find_visited(
    scope: dict[str, Any],
    rows: int,
    columns: int,
) -> tuple[str | None, list[list[bool]]]:
    for name in ("vis", "visited", "seen"):
        value = scope.get(name)
        if not isinstance(value, list) or len(value) < rows:
            continue
        if all(isinstance(row, list) and len(row) >= columns for row in value[:rows]):
            return name, [
                [bool(cell) for cell in row[:columns]]
                for row in value[:rows]
            ]
    for name in REACHED_GRID_NAMES:
        key, value = _scope_lookup(scope, name)
        rows_of = _normalize_grid(_used_rows(value)) if isinstance(value, list) else []
        reached = _reached_test([cell for row in rows_of for cell in row])
        if reached is None:
            continue
        marks = [
            [reached(rows_of[row][column]) if row < len(rows_of) and column < len(rows_of[row]) else False
             for column in range(columns)]
            for row in range(rows)
        ]
        if any(any(row) for row in marks):
            return key, marks
    return None, [[False] * columns for _ in range(rows)]


# Values a distance table starts with for "not reached yet": `-1`, `INF`, `1e9`, `INT_MAX`.
INF_CONSTANTS = frozenset({
    10**9, 10**9 + 7, 10**18, 2**31 - 1, 2**63 - 1, 2**62, 0x3F3F3F3F, 0x3F3F3F3F3F3F3F3F, 10**9 * 2, 10**15, 10**17,
})


def _reached_test(cells: list[Any]) -> Callable[[Any], bool] | None:
    """How to tell a reached cell in a distance table, from the value it starts with.

    `-1` (or any negative) or an `INF` constant marks "not reached", so 0 (the start)
    counts as reached. A table with neither (0 means unreached) marks only nonzero cells.
    Anything else (not all numbers) cannot be read reliably and marks nothing.
    """
    numbers = [cell for cell in cells if _is_number(cell)]
    if not numbers or len(numbers) != len(cells):
        return None
    if any(number < 0 for number in numbers):
        return lambda cell: _is_number(cell) and cell >= 0
    if any(_is_infinity(number) for number in numbers):
        return lambda cell: _is_number(cell) and not _is_infinity(cell)
    return lambda cell: _is_number(cell) and cell != 0


def _is_infinity(value: Any) -> bool:
    if isinstance(value, float):
        return value == float("inf") or value >= 1e9 and value in {1e9, 1e18, 2e9}
    return _is_index(value) and abs(value) in INF_CONSTANTS


def _active_cells(
    scope: dict[str, Any],
    rows: int,
    columns: int,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Cells the code is at (`row, col`, a pair `cur`), the names it read them from, and a
    readout per coordinate pair (`row,col = (0, 1)`), also for one off the grid (`nr = -1`),
    which keeps the names out of Variables whether or not the cell is on the grid."""
    # Code that walks with (c, r) uses c for the row, so nc/nr follow that order.
    new_cell = ("nc", "nr") if "c" in scope and "r" in scope else ("nr", "nc")
    patterns = (
        ("row", "col", "current"),
        ("i", "j", "scan"),
        ("c", "r", "current"),
        ("new_row", "new_col", "candidate"),
        (*new_cell, "candidate"),
        ("nx", "ny", "candidate"),
        ("wc", "wr", "candidate"),
        ("x", "y", "current"),
    )
    cells: list[dict[str, Any]] = []
    names: list[str] = []
    readouts: list[str] = []
    seen: set[tuple[int, int, str]] = set()
    # A cell held as a pair: `pii now = q.front();`
    for name in ("now", "cur", "current", "cell", "top", "front", "u"):
        value = scope.get(name)
        if (
            isinstance(value, list)
            and len(value) == 2
            and all(_is_index(item) for item in value)
            and 0 <= value[0] < rows
            and 0 <= value[1] < columns
        ):
            names.append(name)
            readouts.append(f"{name} = ({value[0]}, {value[1]})")
            seen.add((value[0], value[1], "current"))
            cells.append({"row": value[0], "column": value[1], "role": "current"})
            break
    for row_name, column_name, role in patterns:
        row, column = scope.get(row_name), scope.get(column_name)
        if not _is_index(row) or not _is_index(column):
            continue
        names.extend((row_name, column_name))
        inside = 0 <= row < rows and 0 <= column < columns
        readouts.append(f"{row_name},{column_name} = ({row}, {column}){'' if inside else ' off the grid'}")
        if not inside:
            continue
        marker = (row, column, role)
        if marker not in seen:
            cells.append({"row": row, "column": column, "role": role})
            seen.add(marker)
    return cells, names, readouts


def _frontier_cells(
    scope: dict[str, Any],
    rows: int,
    columns: int,
) -> tuple[str | None, list[dict[str, int]]]:
    def cell_list(value: Any) -> bool:
        return isinstance(value, list) and all(
            isinstance(item, list) and len(item) == 2 and all(_is_index(part) for part in item)
            for item in value
        )

    frontier_name = next(
        (name for name in ("stack", "queue", "frontier", "q", "que", "st") if cell_list(scope.get(name))),
        None,
    ) or next(
        (name for name, value in scope.items() if value and cell_list(value)),
        None,
    )
    frontier = scope[frontier_name] if frontier_name else []
    cells = []
    for item in frontier[:MAX_VISUAL_ITEMS]:
        if (
            isinstance(item, list)
            and len(item) >= 2
            and isinstance(item[0], int)
            and isinstance(item[1], int)
            and 0 <= item[0] < rows
            and 0 <= item[1] < columns
        ):
            cells.append({"row": item[0], "column": item[1]})
    return frontier_name, cells


def _preferred_values(
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


def _normalize_grid(value: list[Any]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for row in value:
        if isinstance(row, str):
            rows.append(list(row))
        elif isinstance(row, list):
            rows.append(row)
    return rows


def _used_rows(value: Any) -> Any:
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


def _is_grid(value: Any) -> bool:
    # A set of pairs (`set<pair<int,int>>`, `{(r, c)}`) has no rows to line up.
    if isinstance(value, _SetItems):
        return False
    value = _used_rows(value)
    if not isinstance(value, list) or not value:
        return False
    if all(isinstance(row, str) and row for row in value):
        widths = {len(row) for row in value}
        return len(widths) == 1 and min(widths) >= 2
    if all(isinstance(row, list) and row for row in value):
        widths = {len(row) for row in value}
        return len(widths) == 1
    return False


def _is_numeric_array(value: Any) -> bool:
    return _numeric_array_projection(value) is not None


def _numeric_array_projection(
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


def _is_bool_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, bool) for item in value)


def _is_flag_array(value: list[Any], numeric_nodes: list[int]) -> bool:
    """Distinguish `visited[node] = True` arrays from lists of visited nodes."""
    if not value:
        return False
    if all(isinstance(item, bool) for item in value):
        return True
    return (
        all(_is_index(item) and item in (0, 1) for item in value)
        and bool(numeric_nodes)
        and len(value) > max(numeric_nodes)
    )


def _adjacency_rows(value: Any) -> list[tuple[Any, list[tuple[Any, Any]]]] | None:
    """`(source, [(target, weight or None), ...])` per row of an adjacency list or dict.

    Weighted C++ lists hold pairs (`vector<pair<int,int>> adj[N]`); the vertex is the element
    that is always a valid row index, the first one when both are.
    """
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
        isinstance(target, list) and len(target) == 2 and all(_is_number(item) for item in target)
        for target in flattened
    )
    if pairs:
        limit = len(rows) if isinstance(value, list) else None
        for position in (0, 1):
            if all(
                _is_index(target[position]) and target[position] >= 0
                and (limit is None or target[position] < limit)
                for target in flattened
            ):
                return [
                    (source, [(target[position], target[1 - position]) for target in targets])
                    for source, targets in rows
                ]
        return None
    if isinstance(value, list) and not all(_is_index(target) and target >= 0 for target in flattened):
        return None
    return [(source, [(target, None) for target in targets]) for source, targets in rows]


# Names that announce an adjacency list even when every vertex has the same degree.
ADJACENCY_NAMES = frozenset({"graph", "g", "adj", "adjacency", "edges", "children", "child", "tree", "nbr", "nxt"})


def _is_adjacency(value: Any, name: str | None = None) -> bool:
    rows = _adjacency_rows(value)
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
