"""Regressions found by tracing a solution to every CSES problem."""
import shutil

import pytest

from app.analyzer import _adjacency_rows, _graph_frontier, _is_adjacency, _runtime_shapes
from app.cpp_runner import _alias_variables
from app.inputs import input_values
from app.runner import run_debugger

requires_cpp = pytest.mark.skipif(
    not shutil.which("g++") or not shutil.which("gdb"),
    reason="C++ toolchain unavailable",
)


def test_weighted_adjacency_lists_give_edges_with_weights() -> None:
    adj = [[], [[2, 6], [3, 2]], [], [[2, 3]]]

    assert _is_adjacency(adj)
    assert _adjacency_rows(adj)[1] == (1, [(2, 6), (3, 2)])
    # {weight, vertex} pairs: only the second item is always a vertex.
    assert _adjacency_rows([[], [[60, 2]], [[30, 1]]])[1] == (1, [(2, 60)])


def test_dijkstra_queue_of_distance_vertex_pairs_is_the_frontier() -> None:
    name, items = _graph_frontier({"pq": [[0, 1], [7, 3]]}, {"1", "2", "3"})

    assert (name, items) == ("pq", ["1", "3"])


def test_equal_length_tables_are_graphs_only_under_graph_names() -> None:
    table = [[0, 1, 2], [1, 0, 2], [2, 2, 0]]

    assert not _is_adjacency(table, "ways")
    assert _is_adjacency(table, "adj")
    assert "graph" not in _runtime_shapes([{"pre": table, "ways": table}])


def test_pair_vectors_are_not_wide_matrices() -> None:
    shapes = _runtime_shapes([{"x": [[3, 0], [1, 1], [2, 2]], "a": [[1, 2, 3], [4, 5, 6]]}])

    assert "matrix" in shapes and "wide_matrix" in shapes
    assert "wide_matrix" not in _runtime_shapes([{"x": [[3, 0], [1, 1], [2, 2]]}])


def test_references_pointers_and_iterators_are_alias_names() -> None:
    code = "for (auto &x : a) {\nint *p = &a[2];\nconst auto &y = a;\nauto it = s.begin();\nx = a & b;\n"

    assert _alias_variables(code) == {"x", "p", "it"}


def step(line, locals_=None, function="main"):
    return {"line": line, "function": function, "locals": locals_ or {}, "globals": {}}


def number(value):
    return {"type": "int", "value": value}


def test_values_read_inside_a_loop_are_not_input_values_even_when_they_repeat() -> None:
    source = "int t;\ncin >> t;\nwhile (t--) {\n    cin >> x1;\n}"
    steps = [
        step(2, {"t": number(0), "x1": number(0)}),
        step(3, {"t": number(2), "x1": number(0)}),
        step(4, {"t": number(1), "x1": number(0)}),
        step(3, {"t": number(1), "x1": number(5)}),
        step(4, {"t": number(0), "x1": number(5)}),
        step(5, {"t": number(0), "x1": number(5)}),
    ]

    assert [entry["name"] for entry in input_values(source, "cpp", steps)[-1]] == []


def test_only_the_variable_read_by_cin_counts_on_a_one_line_loop() -> None:
    source = "int n, top = 0;\ncin >> n;\nfor (int i = 0; i < n; i++) { cin >> x; top = max(top, x); }\nreturn 0;"
    steps = [
        step(2, {"n": number(0), "top": number(0)}),
        step(3, {"n": number(2), "top": number(0)}),
        step(4, {"n": number(2), "top": number(9)}),
    ]

    assert [entry["name"] for entry in input_values(source, "cpp", steps)[-1]] == ["n"]


@requires_cpp
def test_cpp_newlines_printed_alone_reach_stdout() -> None:
    result = run_debugger(
        "#include <iostream>\n"
        "using namespace std;\n"
        "int main() {\n"
        "    for (int i = 0; i < 2; i++) {\n"
        "        cout << i;\n"
        "        cout << \"\\n\";\n"
        "    }\n"
        "}\n",
        language="cpp",
    )

    assert result["steps"][-1]["stdout"] == "0\n1\n"


@requires_cpp
def test_cached_globals_see_writes_through_references_and_pointers() -> None:
    result = run_debugger(
        "#include <bits/stdc++.h>\n"
        "using namespace std;\n"
        "int a[5];\n"
        "int main() {\n"
        "    for (auto &x : a) {\n"
        "        cin >> x;\n"
        "    }\n"
        "    int *p = &a[2];\n"
        "    *p = 99;\n"
        "    int total = 0;\n"
        "    return total;\n"
        "}\n",
        language="cpp",
        stdin_text="1 2 3 4 5\n",
    )

    values = [[item["value"] for item in step["globals"]["a"]["items"][:5]] for step in result["steps"]]
    line_six = [row for row, step in zip(values, result["steps"]) if step["line"] == 6]
    assert line_six[1] == [1, 0, 0, 0, 0]
    after_pointer = next(row for row, step in zip(values, result["steps"]) if step["line"] == 10)
    assert after_pointer == [1, 2, 99, 4, 5]


@requires_cpp
def test_dijkstra_is_drawn_as_a_weighted_graph() -> None:
    result = run_debugger(
        "#include <bits/stdc++.h>\n"
        "using namespace std;\n"
        "vector<pair<int,int>> adj[10];\n"
        "long long dist[10];\n"
        "int main() {\n"
        "    int n, m;\n"
        "    cin >> n >> m;\n"
        "    for (int i = 0; i < m; i++) { int a, b, c; cin >> a >> b >> c; adj[a].push_back({b, c}); }\n"
        "    for (int i = 1; i <= n; i++) dist[i] = LLONG_MAX;\n"
        "    dist[1] = 0;\n"
        "    priority_queue<pair<long long,int>, vector<pair<long long,int>>, greater<pair<long long,int>>> pq;\n"
        "    pq.push({0, 1});\n"
        "    while (!pq.empty()) {\n"
        "        auto [d, u] = pq.top(); pq.pop();\n"
        "        if (d > dist[u]) continue;\n"
        "        for (auto [v, w] : adj[u]) {\n"
        "            if (dist[u] + w < dist[v]) {\n"
        "                dist[v] = dist[u] + w;\n"
        "                pq.push({dist[v], v});\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n",
        language="cpp",
        stdin_text="3 2\n1 2 6\n1 3 2\n",
    )

    assert result["algorithm"]["kind"] == "dijkstra"
    last = result["steps"][-1]["visualization"]
    assert last["renderer"] == "graph"
    assert {(edge["source"], edge["target"], edge.get("weight")) for edge in last["edges"]} == {
        ("1", "2", "6"),
        ("1", "3", "2"),
    }
