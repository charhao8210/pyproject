"""Guess which algorithm a program implements from its source code."""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, replace
from typing import Any

from .loops import loop_ranges


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
    # Which element of a weighted adjacency pair is the vertex (0 or 1), read from the code
    # (`w = e.first; v = e.second`); None when the code does not say.
    pair_vertex: int | None = None
    # How each distance table marks "not reached", decided from the whole trace (`find_reached_rules`).
    reached_rules: tuple[tuple[str, str], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "renderer": self.renderer,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "method": "AST and runtime-state heuristics",
        }


class FeatureVisitor(ast.NodeVisitor):
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


def collect_subscripts(source: str) -> frozenset[tuple[str, str]]:
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


def with_focus(profile: AlgorithmProfile, source: str, language: str) -> AlgorithmProfile:
    """Point a generic array profile at the array its loops write (`dp`, `can`), not the input."""
    pointed = _with_pointers(profile, source)
    if pointed is not profile:
        return pointed
    generic = profile.name in GENERIC_ARRAY_PROFILES
    if not generic and profile.kind != "dynamic_programming":
        return profile
    focus = loop_written_arrays(source, language)
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


def loop_written_arrays(source: str, language: str) -> tuple[str, ...]:
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


# Arrays that record which cells/vertices a search has reached.
VISITED_LIKE_NAMES = frozenset(
    {"vis", "visited", "seen", "par", "parent", "back", "mov", "move", "moves", "from", "pre", "prev", "dist", "dis"}
)


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


def classify_cpp(source: str, shapes: set[str]) -> AlgorithmProfile:
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


def classify_python(features: FeatureVisitor, shapes: set[str]) -> AlgorithmProfile:
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


WEIGHT_NAMES = frozenset({"w", "wt", "weight", "c", "cost", "len", "length", "d", "dis", "dist", "l", "time", "t"})
VERTEX_NAMES = frozenset({"v", "u", "to", "nxt", "next", "b", "y", "node", "child", "nb", "neighbor", "neighbour", "x"})
_PAIR_FIELD = re.compile(r"\b([A-Za-z_]\w*)\s*=\s*[\w\]\[]+\.(first|second)\b")
_PAIR_BINDING = re.compile(
    r"\[\s*([A-Za-z_]\w*)\s*,\s*([A-Za-z_]\w*)\s*\]\s*:\s*[A-Za-z_]\w*\s*\["
    r"|\bfor\s+\(?\s*([A-Za-z_]\w*)\s*,\s*([A-Za-z_]\w*)\s*\)?\s+in\s+[A-Za-z_]\w*\s*\["
)
_PAIR_PUSH = re.compile(r"\.(?:push_back|emplace_back|append)\s*\(\s*(?:\{|make_pair\s*\(|\()?\s*([A-Za-z_]\w*)\s*,\s*([A-Za-z_]\w*)")


def pair_vertex_position(source: str) -> int | None:
    """Which element of `(a, b)` adjacency pairs is the vertex, from how the code names them:
    `w = edge.first; v = edge.second`, `for (auto [v, w] : adj[u])`, `adj[a].push_back({b, c})`.
    Both elements can be valid vertex numbers (`(1, 2)`), so the data alone cannot tell."""
    code = source
    for short, full in (("f", "first"), ("s", "second")):
        if re.search(rf"#\s*define\s+{short}\s+{full}\b", code):
            code = re.sub(rf"\.{short}\b", f".{full}", code)
    votes = [0, 0]

    def vote(first: str, second: str) -> None:
        for position, name in ((0, first), (1, second)):
            if name in VERTEX_NAMES:
                votes[position] += 1
            elif name in WEIGHT_NAMES:
                votes[1 - position] += 1

    for match in _PAIR_FIELD.finditer(code):
        name, field = match.groups()
        position = 0 if field == "first" else 1
        if name in VERTEX_NAMES:
            votes[position] += 1
        elif name in WEIGHT_NAMES:
            votes[1 - position] += 1
    for match in _PAIR_BINDING.finditer(code):
        first, second = (match.group(1), match.group(2)) if match.group(1) else (match.group(3), match.group(4))
        vote(first, second)
    for match in _PAIR_PUSH.finditer(code):
        vote(*match.groups())
    if votes[0] == votes[1]:
        return None
    return 0 if votes[0] > votes[1] else 1
