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


def test_an_unwound_python_exception_names_the_line_that_raised_it() -> None:
    result = run_debugger(
        "def check(x):\n"
        "    if x < 0:\n"
        "        raise ValueError('negative')\n"
        "    return x\n"
        "print(check(-1))\n"
    )

    final = result["steps"][-1]
    assert final["event"] == "exception" and final["line"] == 5
    assert final["exception"]["origin"] == {"line": 3, "function": "check"}


@requires_cpp
def test_cpp_exit_codes_are_decimal_and_asserts_name_their_condition() -> None:
    source = (
        "#include <bits/stdc++.h>\n"
        "using namespace std;\n"
        "int main() {\n"
        "    int n;\n"
        "    cin >> n;\n"
        "    assert(n > 0);\n"
        "    return 10;\n"
        "}\n"
    )

    assert run_debugger(source, language="cpp", stdin_text="5\n")["error"]["message"] == "Program exited with code 10."
    failed = run_debugger(source, language="cpp", stdin_text="0\n")["error"]
    assert failed == {"type": "AssertionFailed", "message": "assert(n > 0) failed."}


def test_only_lines_that_can_write_a_cached_value_force_a_reread() -> None:
    from app.cpp_runner import _may_write

    reads = [
        "if (nx < 0 || d[nx][ny] != -1) continue;",
        "cout << a[i] << \" \";",
        "best = max(best, dp[i - c[j]]);",
        "while (!q.empty()) {",
        "for (int v : adj[u]) {",
        "if (p[i].first <= x && adj[u].size() > 2) {",
        "dp[a[i]] = 1;",
    ]
    writes = [
        "d[nx][ny] = d[x][y] + 1;",
        "cnt[x]++;",
        "if (++cnt[x] == 2) {",
        "cin >> n >> a[i];",
        "scanf(\"%d\", &a[i]);",
        "swap(a[i], a[j]);",
        "sort(a, a + n);",
        "q.push({x, y});",
        "edges[id].cap -= push;",
        "vector<int> a(n);",
        "solve(a);",
    ]
    assert not _may_write(reads[0], "d") and not _may_write(reads[3], "q") and not _may_write(reads[4], "adj")
    assert not _may_write(reads[5], "p") and not _may_write(reads[5], "adj") and not _may_write(reads[6], "a")
    assert not _may_write(reads[2], "dp") and not _may_write(reads[2], "c") and not _may_write(reads[1], "a")
    names = ["d", "cnt", "cnt", "a", "a", "a", "a", "q", "edges", "a", "a"]
    assert [_may_write(statement, name) for statement, name in zip(writes, names)] == [True] * len(writes)


def test_auto_draws_the_array_the_loops_write_not_the_input() -> None:
    from app.analyzer import _loop_written_arrays

    source = (
        "n, x = map(int, input().split())\n"
        "c = list(map(int, input().split()))\n"
        "dp = [0] * (x + 1)\n"
        "dp[0] = 1\n"
        "for s in range(1, x + 1):\n"
        "    for coin in c:\n"
        "        dp[s] = (dp[s] + dp[s - coin]) % 7\n"
    )
    assert _loop_written_arrays(source, "python") == ("dp",)
    result = run_debugger(source, stdin_text="3 4\n1 2 3\n")
    assert result["algorithm"]["kind"] == "dynamic_programming"
    assert {step["visualization"].get("name") for step in result["steps"] if step["visualization"].get("ready")} == {"dp"}


def test_sets_of_pairs_are_not_grids() -> None:
    assert "matrix" not in _runtime_shapes([{"ranked": __import__("app.analyzer", fromlist=["_SetItems"])._SetItems([[1, 2], [3, 4]])}])


def test_writes_through_a_ternary_group_and_later_declarators_count() -> None:
    from app.cpp_runner import _may_write

    assert _may_write("(d % 2 ? white : black).push_back(len);", "white")
    assert _may_write("(d % 2 ? white : black).push_back(len);", "black")
    assert _may_write("vector<int> p(n), q(n);", "q")
    assert not _may_write("x = (a[i] + 1) * 2;", "a")


def test_a_map_subscript_is_a_write() -> None:
    from app.cpp_runner import _may_write

    assert _may_write("count += seen[prefix - x];", "seen", subscript_reads=False)
    assert not _may_write("count += seen[prefix - x];", "seen")


def test_an_alias_writes_only_what_it_was_bound_to() -> None:
    from app.cpp_runner import _alias_targets

    code = "for (auto &[u, v] : edges) { cin >> u; }\nEdge &e = edges[id];\nint *p = &a[2];\n*p = 99;\nint &r = get(i);\n"

    assert {"edges"} <= _alias_targets(code, "u") and {"edges"} <= _alias_targets(code, "v")
    assert _alias_targets(code, "e") == {"edges", "id"}
    assert _alias_targets(code, "p") == {"a"}
    # A function can return a reference to anything.
    assert _alias_targets(code, "r") is None


def test_each_line_carries_the_values_and_cells_it_will_change() -> None:
    result = run_debugger(
        "x = 7\n"
        "a = [0, 0, 0]\n"
        "g = [[0, 0], [0, 0]]\n"
        "x += 3\n"
        "a[1] = 5\n"
        "g[1][0] = 2\n"
        "s = {1}\n"
        "s.add(4)\n"
        "done = 1\n"
    )
    usage = {}
    for step in result["steps"]:
        usage.setdefault(step["line"], step["usage"])

    # Each effect belongs to the step showing the line that makes it.
    assert (usage[4]["next"]["x"]["type"], usage[4]["next"]["x"]["value"]) == ("int", 10)
    assert usage[5]["cells"]["a"] == {"items": [1], "cells": []}
    assert usage[6]["cells"]["g"] == {"items": [1], "cells": [[1, 0]]}
    assert usage[8]["cells"]["s"]["items"] == [1] and "s" not in usage[8]["next"]
    assert usage[5]["next"] == {} and usage[9]["cells"] == {}
