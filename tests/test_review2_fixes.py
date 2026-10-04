"""Regressions from the second review of the views and Variables (2026-10-04)."""
import shutil

import pytest

from app.runner import run_debugger

requires_cpp = pytest.mark.skipif(
    not shutil.which("g++") or not shutil.which("gdb"),
    reason="C++ toolchain unavailable",
)

WEIGHT_VERTEX = (
    '#include <bits/stdc++.h>\n'
    'using namespace std;\n'
    'int main() {\n'
    '    int n = 3;\n'
    '    vector<vector<pair<int,int>>> adj(n + 1);\n'
    '    adj[1].push_back({1, 2});\n'
    '    adj[2].push_back({2, 3});\n'
    '    vector<long long> dist(n + 1, LLONG_MAX);\n'
    '    priority_queue<pair<long long,int>, vector<pair<long long,int>>, greater<>> pq;\n'
    '    dist[1] = 0;\n'
    '    pq.push({0, 1});\n'
    '    while (!pq.empty()) {\n'
    '        auto [d, u] = pq.top(); pq.pop();\n'
    '        if (d != dist[u]) continue;\n'
    '        for (auto edge : adj[u]) {\n'
    '            int w = edge.first;\n'
    '            int v = edge.second;\n'
    '            if (dist[u] + w < dist[v]) {\n'
    '                dist[v] = dist[u] + w;\n'
    '                pq.push({dist[v], v});\n'
    '            }\n'
    '        }\n'
    '    }\n'
    '    for (int i = 1; i <= n; i++) cout << dist[i] << " ";\n'
    '}\n'
)
GRID_ALL = (
    '#include <bits/stdc++.h>\n'
    'using namespace std;\n'
    'int n, m;\n'
    'char g[5][5];\n'
    'int dist[5][5];\n'
    'int dx[4] = {1, -1, 0, 0}, dy[4] = {0, 0, 1, -1};\n'
    'int main() {\n'
    '    cin >> n >> m;\n'
    '    for (int i = 0; i < n; i++) cin >> g[i];\n'
    '    memset(dist, -1, sizeof dist);\n'
    '    queue<pair<int,int>> q;\n'
    '    q.push({0, 0});\n'
    '    dist[0][0] = 0;\n'
    '    while (!q.empty()) {\n'
    '        auto cur = q.front(); q.pop();\n'
    '        for (int k = 0; k < 4; k++) {\n'
    '            int nr = cur.first + dx[k], nc = cur.second + dy[k];\n'
    '            if (nr < 0 || nc < 0 || nr >= n || nc >= m) continue;\n'
    "            if (g[nr][nc] == '#' || dist[nr][nc] != -1) continue;\n"
    '            dist[nr][nc] = dist[cur.first][cur.second] + 1;\n'
    '            q.push({nr, nc});\n'
    '        }\n'
    '    }\n'
    '    cout << dist[n-1][m-1] << endl;\n'
    '}\n'
)
GRID_ALL_INPUT = '2 3\n...\n...\n'
PARALLEL = (
    '#include <bits/stdc++.h>\n'
    'using namespace std;\n'
    'int main() {\n'
    '    int n, m;\n'
    '    cin >> n >> m;\n'
    '    vector<vector<pair<int,int>>> adj(n + 1);\n'
    '    for (int i = 0; i < m; i++) {\n'
    '        int a, b, c;\n'
    '        cin >> a >> b >> c;\n'
    '        adj[a].push_back({b, c});\n'
    '    }\n'
    '    vector<long long> dist(n + 1, LLONG_MAX);\n'
    '    priority_queue<pair<long long,int>, vector<pair<long long,int>>, greater<>> pq;\n'
    '    dist[1] = 0;\n'
    '    pq.push({0, 1});\n'
    '    while (!pq.empty()) {\n'
    '        auto [d, u] = pq.top(); pq.pop();\n'
    '        if (d != dist[u]) continue;\n'
    '        for (auto [v, w] : adj[u]) {\n'
    '            if (dist[u] + w < dist[v]) {\n'
    '                dist[v] = dist[u] + w;\n'
    '                pq.push({dist[v], v});\n'
    '            }\n'
    '        }\n'
    '    }\n'
    '    for (int i = 1; i <= n; i++) cout << dist[i] << " ";\n'
    '}\n'
)
PARALLEL_INPUT = '3 4\n1 2 6\n1 3 2\n3 2 3\n1 3 4\n'
RECIPROCAL = (
    '#include <bits/stdc++.h>\n'
    'using namespace std;\n'
    'int main() {\n'
    '    int n, m;\n'
    '    cin >> n >> m;\n'
    '    vector<vector<int>> adj(n + 1);\n'
    '    for (int i = 0; i < m; i++) {\n'
    '        int u, v;\n'
    '        cin >> u >> v;\n'
    '        adj[u].push_back(v);\n'
    '    }\n'
    '    vector<bool> vis(n + 1);\n'
    '    queue<int> q;\n'
    '    q.push(1); vis[1] = true;\n'
    '    while (!q.empty()) {\n'
    '        int u = q.front(); q.pop();\n'
    '        for (int v : adj[u]) if (!vis[v]) { vis[v] = true; q.push(v); }\n'
    '    }\n'
    '    cout << n << endl;\n'
    '}\n'
)
RECIPROCAL_INPUT = '3 4\n1 2\n2 1\n2 3\n3 2\n'


@requires_cpp
def test_weight_first_pairs_are_read_as_weight_then_vertex() -> None:
    # `w = edge.first; v = edge.second` with adj[1] = {(1, 2)}: an edge 1 -> 2 of weight 1.
    graph = run_debugger(WEIGHT_VERTEX, language="cpp")["steps"][-1]["visualization"]
    assert graph["pair_order"] == "(weight, vertex)"
    assert [(edge["source"], edge["target"], edge["weight"]) for edge in graph["edges"]] == [("1", "2", "1"), ("2", "3", "2")]


def test_pair_order_follows_how_the_code_names_the_elements() -> None:
    from app.analyzer import _pair_vertex_position

    assert _pair_vertex_position("for (auto [v, w] : adj[u])") == 0
    assert _pair_vertex_position("int w = e.first; int v = e.second;") == 1
    assert _pair_vertex_position("adj[a].push_back({b, c});") == 0
    assert _pair_vertex_position("adj[a].push_back({c, b});") == 1
    assert _pair_vertex_position("int x = 1;") is None


def test_repeated_large_numbers_are_not_infinity_without_an_inf_in_the_code() -> None:
    steps = run_debugger("prices = [1000000000, 1000000000, 3]\ntotal = sum(prices)\n")["steps"]
    assert all("infinite" not in step["visualization"] for step in steps)


@requires_cpp
def test_the_start_cell_stays_visited_after_every_cell_is_reached() -> None:
    steps = run_debugger(GRID_ALL, stdin_text=GRID_ALL_INPUT, language="cpp")["steps"]
    grids = [step["visualization"] for step in steps if step["visualization"].get("renderer") == "grid"]
    final = grids[-1]["visited"]
    assert all(final[row][column] for row in range(2) for column in range(3))
    first = next(index for index, grid in enumerate(grids) if grid["visited"][0][0])
    assert all(grid["visited"][0][0] for grid in grids[first:])


def test_isolated_vertices_are_drawn_and_visited_stays_listed_when_not_all_drawn() -> None:
    source = (
        "n = 4\n"
        "adj = [[1], [0], [], []]\n"
        "vis = [False] * n\n"
        "stack = [0]\n"
        "vis[0] = True\n"
        "while stack:\n"
        "    u = stack.pop()\n"
        "    for v in adj[u]:\n"
        "        if not vis[v]:\n"
        "            vis[v] = True\n"
        "            stack.append(v)\n"
    )
    graph = run_debugger(source)["steps"][-1]["visualization"]
    assert graph["nodes"] == ["0", "1", "2", "3"] and graph["visited"] == ["0", "1"]


@requires_cpp
def test_only_the_parallel_edge_being_checked_is_named() -> None:
    steps = run_debugger(PARALLEL, stdin_text=PARALLEL_INPUT, language="cpp")["steps"]
    checks = [step["visualization"]["checking"] for step in steps if step["visualization"].get("checking")]
    to_three = [check for check in checks if check["target"] == "3" and check["source"] == "1"]
    assert {check["weight"] for check in to_three} == {"2", "4"}


@requires_cpp
def test_a_symmetric_directed_graph_keeps_all_its_edges_for_the_direction_switch() -> None:
    graph = run_debugger(RECIPROCAL, stdin_text=RECIPROCAL_INPUT, language="cpp")["steps"][-1]["visualization"]
    assert graph["directed"] is False  # only a guess: every edge is stored both ways
    assert len(graph["edges"]) == 4 and len(graph["undirected"]) == 2


@requires_cpp
def test_an_emptied_queue_is_drawn_empty_not_as_its_last_state() -> None:
    steps = run_debugger(GRID_ALL, stdin_text=GRID_ALL_INPUT, language="cpp")["steps"]
    final = steps[-1]["views"]
    for view_id in ("array:q", "cells:q"):
        assert final[view_id]["ready"] and final[view_id]["values"] == [] and not final[view_id].get("carried")


def test_objects_list_their_fields() -> None:
    source = (
        "class Node:\n"
        "    def __init__(self, value):\n"
        "        self.value = value\n"
        "        self.next = None\n"
        "head = Node(1)\n"
        "head.next = Node(20)\n"
        "head.value = 10\n"
        "head.next.value = 99\n"
        "done = 1\n"
    )
    head = run_debugger(source)["steps"][-1]["locals"]["head"]
    assert head["type"] == "dict" and head["class_name"] == "Node"
    fields = {entry["key"]["value"]: entry["value"] for entry in head["entries"]}
    assert fields["value"]["value"] == 10
    inner = {entry["key"]["value"]: entry["value"] for entry in fields["next"]["entries"]}
    assert inner["value"]["value"] == 99


def test_every_array_can_be_picked_and_later_ones_are_computed_on_request() -> None:
    source = "".join(f"a{index} = [{index}0, {index}1, {index}2]\n" for index in range(1, 8)) + "a7[1] = 99\n"
    result = run_debugger(source)
    views = {view["id"]: view for view in result["algorithm"]["views"]}
    assert views["array:a7"].get("pending") and "array:a7" not in result["steps"][-1]["views"]
    again = run_debugger(source, extra_views=["array:a7"])
    assert again["steps"][-1]["views"]["array:a7"]["values"] == [70, 99, 72]
