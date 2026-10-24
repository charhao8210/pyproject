"""The graph and union-find views."""
from __future__ import annotations

import re
from typing import Any, Iterable

from .values import (
    MAX_VISUAL_ITEMS,
    PartialItems,
    adjacency_rows,
    display_value,
    is_adjacency,
    is_flag_array,
    is_index,
    is_number,
    logical_length,
    named_values,
    scope_lookup,
    unique_names,
)


def orient_graphs(steps: list[dict[str, Any]]) -> None:
    """Guess once per trace whether each graph is directed; keep every stored edge.

    An undirected adjacency list stores every edge both ways (`adj[a].push_back(b)` and
    `adj[b].push_back(a)`); a directed one (`adj[a].push_back({b, c})` only) does not. The
    fullest state of the graph decides, since an edge is half-stored between its two pushes.
    A directed graph can happen to be symmetric (1→2 and 2→1 both given), so this is only a
    guess: `edges` keeps every stored edge and `undirected` lists the ones to draw (each pair
    once) when the graph is read as undirected; the view lets the user switch.
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
        model["undirected"] = _undirected_edges(model.get("edges") or [])


def _edge_key(edge: dict[str, str], reverse: bool = False) -> tuple[str, str, Any]:
    ends = (edge["target"], edge["source"]) if reverse else (edge["source"], edge["target"])
    return (*ends, edge.get("weight"))


def _symmetric(edges: list[dict[str, str]]) -> bool:
    counts: dict[tuple[str, str, Any], int] = {}
    for edge in edges:
        counts[_edge_key(edge)] = counts.get(_edge_key(edge), 0) + 1
    return all(counts.get((target, source, weight), 0) == count for (source, target, weight), count in counts.items())


def _undirected_edges(edges: list[dict[str, str]]) -> list[int]:
    """Positions of the edges an undirected drawing keeps: each stored pair `a → b`, `b → a`
    once; two edges between the same vertices stay two."""
    pending: dict[tuple[str, str, Any], int] = {}
    kept = []
    for position, edge in enumerate(edges):
        reverse = _edge_key(edge, reverse=True)
        if pending.get(reverse):
            pending[reverse] -= 1
            continue
        pending[_edge_key(edge)] = pending.get(_edge_key(edge), 0) + 1
        kept.append(position)
    return kept


# Lists of pairs under these names record visits, and these tables hold values, not edges.
NOT_A_GRAPH_NAMES = frozenset({
    "vis", "visited", "seen", "used", "done",
    "dp", "memo", "dist", "dis", "d", "cnt", "cost", "pre", "pref", "prefix", "ps", "sum", "sums",
    "up", "anc", "lift", "jump", "sp",
})


def graph_visualization(
    scope: dict[str, Any],
    graph_name: str | None = None,
    vertex_position: int | None = None,
) -> dict[str, Any]:
    for name, value in named_values(scope, graph_name, ("graph", "g", "adj", "adjacency")):
        if not is_adjacency(value, name) or (graph_name is None and name.lower() in NOT_A_GRAPH_NAMES):
            continue
        chosen: list[int] = []
        adjacency = adjacency_rows(value, vertex_position, chosen) or []
        if isinstance(value, dict):
            node_values = {source for source, _ in adjacency}
        else:
            node_values = {source for source, targets in adjacency if targets}
            # Fixed-size C++ adjacency arrays have many unused rows; only keep
            # isolated vertices inside the logical 0..n-1 or 1..n range. A list of exactly n
            # rows is 0-indexed (`adj = [[1], [0], [], []]` has vertices 0..3).
            count = scope.get("n")
            if is_index(count) and 0 < count <= len(value):
                first = 0 if count == len(value) else (1 if not value[0] else 0)
                node_values.update(range(first, first + count))
        edges: list[dict[str, str]] = []
        for source, targets in adjacency:
            for target, weight in targets:
                node_values.add(target)
                edge = {"source": str(source), "target": str(target)}
                if weight is not None:
                    edge["weight"] = display_value(weight, "cpp")
                edges.append(edge)
        visited_name, visited_value = next(
            (
                (key, scope[key])
                for key in ("visited", "vis", "seen", "par", "parent")
                if key in scope
            ),
            (None, []),
        )
        numeric_nodes = [node for node in node_values if is_index(node)]
        if isinstance(visited_value, list) and visited_name in {"par", "parent"}:
            visited = [
                str(index)
                for index, item in enumerate(visited_value)
                if item not in (0, False)
            ]
        elif isinstance(visited_value, list) and is_flag_array(visited_value, numeric_nodes):
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
        frontier_name, frontier, frontier_entries = graph_frontier(scope, node_ids)
        label_name, labels = _graph_labels(scope, numeric_nodes, {name} if visited_name in GRAPH_LABEL_NAMES else {name, visited_name})
        parents = _tree_parents(node_values, edges)
        route_name, route = _graph_route(scope, node_ids, edges, current)
        return {
            "renderer": "graph",
            "ready": True,
            "name": name,
            "uses": unique_names([
                name,
                # A visited array covering vertices the graph does not draw stays in Variables.
                visited_name if isinstance(visited_value, list) and _covers(visited_value, node_values) else None,
                current_name,
                checking["to_name"] if checking else None,
                checking.get("weight_name") if checking else None,
                frontier_name,
                route_name,
            ]),
            # The edge from the current vertex to the neighbour it is looking at (and its weight,
            # which tells parallel edges apart).
            "checking": (
                {key: checking[key] for key in ("source", "target", "weight") if key in checking}
                if checking
                else None
            ),
            "nodes": sorted(str(node) for node in node_values),
            "edges": edges[:100],
            "edges_total": len(edges),
            "edges_truncated": len(edges) > 100,
            "capture_truncated": isinstance(value, PartialItems) or any(isinstance(row, PartialItems) for row in value if isinstance(value, list)),
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
            # Which pair element was taken for the vertex, said on screen since it is inferred.
            "pair_order": (
                ("(vertex, weight)" if chosen[0] == 0 else "(weight, vertex)") if chosen else None
            ),
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
        key, value = scope_lookup(scope, name)
        if not isinstance(value, list) or not value:
            continue
        items = [str(item) for item in value if is_index(item)]
        if len(items) != len(value) or not all(item in node_ids for item in items):
            continue
        last = items[-1]
        extends = current is not None and current != last and ((last, current) in joined or (current, last) in joined)
        return key, {"name": key, "items": items, **({"next": current} if extends else {})}
    return None, None


def _covers(flags: list[Any], node_values: set[Any]) -> bool:
    """Every set entry of a per-vertex array belongs to a drawn vertex."""
    drawn = {str(node) for node in node_values}
    return all(str(index) in drawn for index, flag in enumerate(flags) if flag not in (0, False, None, -1))


REACHED_VERTEX_NAMES = ("team", "color", "colour", "side", "dist", "dis", "depth", "level", "comp")


def _reached_vertices(scope: dict[str, Any], numeric_nodes: list[int]) -> tuple[str | None, list[str]]:
    """Vertices a search has reached, read from a per-vertex state array: anything but
    0/-1/false, and not an 'infinity' placeholder."""
    for name in REACHED_VERTEX_NAMES:
        key, value = scope_lookup(scope, name)
        if not isinstance(value, list) or not numeric_nodes:
            continue
        reached = [
            str(node)
            for node in numeric_nodes
            if 0 <= node < len(value)
            and is_number(value[node])
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
        if not is_index(source):
            continue
        for target_name in NEIGHBOUR_NAMES:
            target = scope.get(target_name)
            if target_name == source_name or not is_index(target):
                continue
            if (str(source), str(target)) in joined or (str(target), str(source)) in joined:
                found = {"from_name": source_name, "to_name": target_name, "source": str(source), "target": str(target)}
                # Two edges can join the same vertices (`1 → 3` with weights 2 and 4): the
                # weight variable in scope says which one is being looked at.
                weights = {
                    edge.get("weight")
                    for edge in edges
                    if {edge["source"], edge["target"]} == {str(source), str(target)} and edge.get("weight") is not None
                }
                for weight_name in WEIGHT_VARIABLE_NAMES:
                    weight = scope.get(weight_name)
                    if is_number(weight) and display_value(weight, "cpp") in weights:
                        found["weight"] = display_value(weight, "cpp")
                        found["weight_name"] = weight_name
                        break
                return found
    return None


WEIGHT_VARIABLE_NAMES = ("w", "wt", "weight", "c", "cost", "len", "length")
GRAPH_FRONTIER_NAMES = ("q", "queue", "que", "frontier", "st", "stack", "pq")
# Per-node arrays worth printing beside each vertex, most useful first.
GRAPH_LABEL_NAMES = (
    "dis", "dist", "distance", "d", "depth", "level", "color", "colour", "team",
    "comp", "component", "sub", "subtree", "sz", "size", "cnt",
    "par", "parent", "p", "prev", "pre", "from",
)


def graph_frontier(scope: dict[str, Any], node_ids: set[str]) -> tuple[str | None, list[str], list[str] | None]:
    """The BFS queue or DFS stack: a list whose entries are all vertices of the graph.

    Dijkstra's priority queue holds (distance, vertex) pairs; the vertex is the second item
    (or the first, when only that one is always a vertex).
    """
    for name in GRAPH_FRONTIER_NAMES:
        key, value = scope_lookup(scope, name)
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
        key, value = scope_lookup(scope, name)
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


def union_find_parent(source: str) -> tuple[str | None, int]:
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


def union_find_visualization(
    scope: dict[str, Any],
    name: str | None = None,
    first: int = 0,
) -> dict[str, Any]:
    """Draw a parent array as a forest: an arrow from every vertex to its parent."""
    for key, value in named_values(scope, name, PARENT_NAMES):
        if not isinstance(value, list) or not all(is_index(item) for item in value):
            continue
        values = value[: min(logical_length(scope, value), MAX_FOREST_NODES)]
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
                if is_index(scope.get(candidate)) and scope[candidate] in node_set
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
            "uses": unique_names([key, current_name, label_name]),
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
