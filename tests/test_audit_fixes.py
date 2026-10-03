"""Regressions from a review of what Variables and the visualizer claim (2026-10-04)."""
import shutil

import pytest

from app.main import _mark_large_integers
from app.runner import run_debugger

requires_cpp = pytest.mark.skipif(
    not shutil.which("g++") or not shutil.which("gdb"),
    reason="C++ toolchain unavailable",
)

GRID_BFS = (
    '#include <bits/stdc++.h>\n'
    'using namespace std;\n'
    'int n, m;\n'
    'char g[10][10];\n'
    'int dist[10][10];\n'
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
    '        int row = cur.first, col = cur.second;\n'
    '        for (int k = 0; k < 4; k++) {\n'
    '            int nr = row + dx[k], nc = col + dy[k];\n'
    '            if (nr < 0 || nc < 0 || nr >= n || nc >= m) continue;\n'
    "            if (g[nr][nc] == '#' || dist[nr][nc] != -1) continue;\n"
    '            dist[nr][nc] = dist[row][col] + 1;\n'
    '            q.push({nr, nc});\n'
    '        }\n'
    '    }\n'
    '    cout << dist[n-1][m-1] << endl;\n'
    '}\n'
)
GRID_INPUT = "3 4\n..#.\n.#..\n....\n"
TWO_SUM_CPP = (
    '#include <bits/stdc++.h>\n'
    'using namespace std;\n'
    'int main() {\n'
    '    int n, x;\n'
    '    cin >> n >> x;\n'
    '    vector<int> a(n);\n'
    '    for (int i = 0; i < n; i++) cin >> a[i];\n'
    '    vector<pair<int,int>> pairs;\n'
    '    for (int i = 0; i < n; i++) pairs.push_back({a[i], i + 1});\n'
    '    sort(pairs.begin(), pairs.end());\n'
    '    int l = 0, r = n - 1;\n'
    '    while (l < r) {\n'
    '        int total = pairs[l].first + pairs[r].first;\n'
    '        if (total == x) { cout << pairs[l].second << " " << pairs[r].second << endl; return 0; }\n'
    '        if (total < x) l++;\n'
    '        else r--;\n'
    '    }\n'
    '    cout << "IMPOSSIBLE" << endl;\n'
    '}\n'
)
TWO_SUM_PY = (
    'n, x = 4, 8\n'
    'a = [2, 7, 5, 1]\n'
    'pairs = sorted((value, index + 1) for index, value in enumerate(a))\n'
    'l, r = 0, n - 1\n'
    'while l < r:\n'
    '    total = pairs[l][0] + pairs[r][0]\n'
    '    if total == x:\n'
    '        print(pairs[l][1], pairs[r][1])\n'
    '        break\n'
    '    if total < x:\n'
    '        l += 1\n'
    '    else:\n'
    '        r -= 1\n'
)
LONG_ARRAY_PY = (
    'a = [i % 7 for i in range(80)]\n'
    'i = 70\n'
    'a[i] = 999\n'
    'print(a[70])\n'
)
LONG_ARRAY_CPP = (
    '#include <bits/stdc++.h>\n'
    'using namespace std;\n'
    'int main() {\n'
    '    vector<int> a(80);\n'
    '    for (int i = 0; i < 80; i++) a[i] = i % 7;\n'
    '    int i = 70;\n'
    '    a[i] = 999;\n'
    '    cout << a[70] << endl;\n'
    '}\n'
)
DIJKSTRA = (
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
    '    cout << endl;\n'
    '}\n'
)
UNDIRECTED = (
    '#include <bits/stdc++.h>\n'
    'using namespace std;\n'
    'int main() {\n'
    '    int n = 4;\n'
    '    vector<int> adj[5];\n'
    '    bool vis[5] = {};\n'
    '    int e[3][2] = {{1, 2}, {2, 3}, {1, 4}};\n'
    '    for (auto &x : e) { adj[x[0]].push_back(x[1]); adj[x[1]].push_back(x[0]); }\n'
    '    queue<int> q;\n'
    '    q.push(1); vis[1] = true;\n'
    '    while (!q.empty()) {\n'
    '        int u = q.front(); q.pop();\n'
    '        for (int v : adj[u]) if (!vis[v]) { vis[v] = true; q.push(v); }\n'
    '    }\n'
    '    cout << n << endl;\n'
    '}\n'
)
TYPES = (
    '#include <bits/stdc++.h>\n'
    'using namespace std;\n'
    'int main() {\n'
    '    long long big = 1LL << 40;\n'
    '    string text = "X";\n'
    '    float ratio = 0.5;\n'
    "    char c = 'q';\n"
    '    unsigned int u = 7;\n'
    '    auto z = big * 2;\n'
    '    cout << big << text << ratio << c << u << z << endl;\n'
    '}\n'
)


@requires_cpp
def test_distance_table_marks_reached_cells_not_unreached_ones_or_walls() -> None:
    # dist starts at -1 ("not reached"); the start is 0; `#` cells are never reached.
    steps = run_debugger(GRID_BFS, stdin_text=GRID_INPUT, language="cpp")["steps"]
    grid = steps[-1]["visualization"]
    assert grid["renderer"] == "grid"
    visited = grid["visited"]
    assert visited[0][0], "the start (distance 0) is reached"
    assert not visited[0][2] and not visited[1][1], "walls are never visited"
    assert visited[2][3]
    early = next(
        step["visualization"]
        for step in steps
        if step["visualization"].get("renderer") == "grid" and step["line"] == 15
    )
    assert sum(cell for row in early["visited"] for cell in row) == 1


@requires_cpp
def test_grid_shows_coordinates_and_queue_order() -> None:
    steps = run_debugger(GRID_BFS, stdin_text=GRID_INPUT, language="cpp")["steps"]
    views = [step["visualization"] for step in steps if step["visualization"].get("renderer") == "grid"]
    assert any("row,col = (0, 0)" in view.get("coordinates", []) for view in views)
    assert any(text.endswith("off the grid") for view in views for text in view.get("coordinates", []))
    assert any(view.get("queue") and view["queue"]["entries"] == ["(1, 0)"] for view in views)
    # Off-grid coordinates stay drawn by the view, so they never pop into Variables.
    for view in views:
        if any(text.startswith("nr,nc") for text in view.get("coordinates", [])):
            assert {"nr", "nc"} <= set(view["uses"])


@requires_cpp
def test_two_sum_pointers_mark_the_sorted_pairs_not_the_input() -> None:
    result = run_debugger(TWO_SUM_CPP, stdin_text="4 8\n2 7 5 1\n", language="cpp")
    assert result["algorithm"]["kind"] == "two_pointers"
    view = next(step["visualization"] for step in result["steps"] if step["line"] == 13)
    assert view["name"] == "pairs" and view["values"] == [1, 2, 5, 7]
    assert {marker["label"]: marker["index"] for marker in view["markers"]} == {"l": 0, "r": 3}


def test_python_two_sum_pointers_mark_the_sorted_pairs() -> None:
    result = run_debugger(TWO_SUM_PY)
    view = next(step["visualization"] for step in result["steps"] if step["line"] == 6)
    assert view["name"] == "pairs"
    assert result["algorithm"]["kind"] == "two_pointers"


def test_three_sum_is_named_only_when_the_left_pointer_starts_after_an_outer_index() -> None:
    source = (
        "a = sorted([3, -1, 0, 2, -2])\n"
        "target = 0\n"
        "found = 0\n"
        "for i in range(len(a)):\n"
        "    l, r = i + 1, len(a) - 1\n"
        "    while l < r:\n"
        "        s = a[i] + a[l] + a[r]\n"
        "        if s == target:\n"
        "            found += 1\n"
        "            break\n"
        "        if s < target:\n"
        "            l += 1\n"
        "        else:\n"
        "            r -= 1\n"
        "print(found)\n"
    )
    assert run_debugger(source)["algorithm"]["kind"] == "three_sum"


def test_long_list_says_how_much_is_drawn_and_names_an_index_past_it() -> None:
    view = run_debugger(LONG_ARRAY_PY)["steps"][-1]["visualization"]
    assert view["truncated"] and view["length"] == 80 and len(view["values"]) == 50
    assert view["beyond"] == [{"index": 70, "label": "i"}]


@requires_cpp
def test_long_vector_reports_its_real_size() -> None:
    final = run_debugger(LONG_ARRAY_CPP, language="cpp")["steps"][-1]
    assert final["locals"]["a"]["truncated"] and final["locals"]["a"]["length"] == 80
    view = final["visualization"]
    assert view["length"] == 80 and view["beyond"] == [{"index": 70, "label": "i"}]


def test_bar_values_beyond_2_53_keep_their_exact_digits() -> None:
    result = run_debugger("a = [500000000000000003, 500000000000000004]\nx = a[0]\n")
    _mark_large_integers(result)
    view = result["steps"][-1]["visualization"]
    assert view["values_text"] == ["500000000000000003", "500000000000000004"]


@requires_cpp
def test_directed_graph_keeps_parallel_edges_and_undirected_edges_are_drawn_once() -> None:
    steps = run_debugger(DIJKSTRA, stdin_text="3 4\n1 2 6\n1 3 2\n3 2 3\n1 3 4\n", language="cpp")["steps"]
    graph = steps[-1]["visualization"]
    assert graph["directed"] is True
    into_three = [(edge["source"], edge["weight"]) for edge in graph["edges"] if edge["target"] == "3"]
    assert into_three == [("1", "2"), ("1", "4")]
    frontiers = [step["visualization"].get("frontier") or {} for step in steps]
    assert any(frontier.get("entries") == ["(0, 1)"] for frontier in frontiers)

    graph = run_debugger(UNDIRECTED, language="cpp")["steps"][-1]["visualization"]
    assert graph["directed"] is False
    assert sorted((edge["source"], edge["target"]) for edge in graph["edges"]) == [("1", "2"), ("1", "4"), ("2", "3")]


def test_a_second_name_for_a_list_is_a_reference_to_the_same_object() -> None:
    final = run_debugger("a = [1, 2]\nb = a\nb.append(3)\n")["steps"][-1]["locals"]
    assert final["b"]["type"] == "reference" and final["b"]["object_id"] == final["a"]["object_id"]


@requires_cpp
def test_cpp_values_carry_their_declared_type() -> None:
    final = run_debugger(TYPES, language="cpp")["steps"][-1]["locals"]
    assert {name: value.get("c_type") for name, value in final.items()} == {
        "big": "long long", "text": "string", "ratio": "float", "c": "char", "u": "unsigned int", "z": "auto",
    }


def test_infinity_placeholders_are_marked_apart() -> None:
    source = (
        "INF = 10**9\n"
        "dp = [INF] * 6\n"
        "dp[0] = 0\n"
        "for s in range(1, 6):\n"
        "    dp[s] = dp[s - 1] + 1\n"
        "print(dp)\n"
    )
    steps = run_debugger(source)["steps"]
    view = next(step["visualization"] for step in steps if step["line"] == 4)
    assert view["name"] == "dp" and view["infinite"] == [1, 2, 3, 4, 5]
    assert "infinite" not in steps[-1]["visualization"]


def test_a_single_large_input_value_is_not_taken_for_infinity() -> None:
    steps = run_debugger("a = [1000000000, 3, 4]\nfor i in range(3):\n    a[i] += 1\n")["steps"]
    assert all("infinite" not in step["visualization"] for step in steps)


def test_recursive_code_draws_its_recursion_tree_by_default() -> None:
    result = run_debugger("def fib(n):\n    if n < 2:\n        return n\n    return fib(n - 1) + fib(n - 2)\nprint(fib(4))\n")
    assert result["algorithm"]["auto_renderer"] == "recursion_tree"
    labels = [node["label"] for node in result["algorithm"]["recursion_tree"]["nodes"]]
    assert "fib(4)" in labels and "fib(3)" in labels


@requires_cpp
def test_std_array_variables_are_decoded() -> None:
    source = (
        "#include <bits/stdc++.h>\n"
        "using namespace std;\n"
        "int main() {\n"
        "    array<int, 4> l = {0, 2, 1, 0};\n"
        "    auto dfs = [&](auto dfs, int id, array<int, 4> c) -> void {\n"
        "        if (id == 2) return;\n"
        "        c[id] += 5;\n"
        "        dfs(dfs, id + 1, c);\n"
        "    };\n"
        "    dfs(dfs, 0, l);\n"
        "    cout << l[1] << endl;\n"
        "}\n"
    )
    steps = run_debugger(source, language="cpp")["steps"]
    assert [item["value"] for item in steps[-1]["locals"]["l"]["items"]] == [0, 2, 1, 0]
    inner = [step for step in steps if step["function"] == "dfs" and step["line"] == 8]
    assert [item["value"] for item in inner[-1]["locals"]["c"]["items"]] == [5, 7, 1, 0]


def test_an_index_marker_is_drawn_only_on_the_containers_it_indexes() -> None:
    source = (
        "v = [3, 1, 2]\n"
        "v.sort()\n"
        "l = [0, 0, 0, 0]\n"
        "for i in range(4):\n"
        "    l[i] += v[0]\n"
    )
    steps = run_debugger(source)["steps"]
    body = [step for step in steps if step["line"] == 5]
    assert body
    for step in body:
        assert all(marker["label"] != "i" for marker in step["views"]["array:v"]["markers"])
    assert any(marker["label"] == "i" for step in body for marker in step["views"]["array:l"]["markers"])


BFS = (
    "#include <bits/stdc++.h>\n"
    "using namespace std;\n"
    "int n, m;\n"
    "vector<vector<int>> g;\n"
    "int dis[100005];\n"
    "bool vis[100005];\n"
    "int main() {\n"
    "    cin >> n >> m;\n"
    "    g.resize(n + 1);\n"
    "    for (int i = 0; i < m; i++) {\n"
    "        int a, b; cin >> a >> b;\n"
    "        g[a].push_back(b);\n"
    "        g[b].push_back(a);\n"
    "    }\n"
    "    queue<int> q;\n"
    "    q.push(1);\n"
    "    dis[1] = 1;\n"
    "    vis[1] = true;\n"
    "    while (q.size()) {\n"
    "        int node = q.front();\n"
    "        q.pop();\n"
    "        for (int i = 0; i < g[node].size(); i++) {\n"
    "            int next = g[node][i];\n"
    "            if (!vis[next]) {\n"
    "                dis[next] = dis[node] + 1;\n"
    "                vis[next] = true;\n"
    "                q.push(next);\n"
    "            }\n"
    "        }\n"
    "    }\n"
    "    cout << dis[n] << endl;\n"
    "}\n"
)


@requires_cpp
def test_each_line_shows_its_own_effect_on_the_view() -> None:
    # The user's rule: `vis[1] = true` marks vertex 1 visited on that line's step, not the next.
    steps = run_debugger(BFS, stdin_text="5 5\n1 2\n1 3\n2 3\n1 4\n4 5\n", language="cpp")["steps"]

    def at(line: int) -> dict:
        return next(step["visualization"] for step in steps if step["line"] == line)

    assert at(16)["frontier"]["items"] == ["1"]
    assert at(17)["labels"]["values"]["1"] == 1
    assert at(18)["visited"] == ["1"]
    assert at(20)["current"] == "1"
    assert "2" in at(26)["visited"]
    # The current-line view still describes the step's own line.
    assert all(step["views"]["execution"]["line"] == step["line"] for step in steps)


ROUTE_INPUT = "5 5\n1 2\n1 3\n2 3\n1 4\n4 5\n"
MESSAGE_ROUTE = (
    '#include <bits/stdc++.h>\n'
    'using namespace std;\n'
    'int n, m;\n'
    'vector<vector<int>> g;\n'
    'int dis[100005];\n'
    'bool vis[100005];\n'
    'int main() {\n'
    '    cin >> n >> m;\n'
    '    g.resize(n + 1);\n'
    '    for (int i = 0; i < m; i++) {\n'
    '        int a, b; cin >> a >> b;\n'
    '        g[a].push_back(b);\n'
    '        g[b].push_back(a);\n'
    '    }\n'
    '    // BFS\n'
    '    queue<int> q;\n'
    '    q.push(1);\n'
    '    dis[1] = 1;\n'
    '    vis[1] = true;\n'
    '    while (q.size()) {\n'
    '        int node = q.front();\n'
    '        q.pop();\n'
    '        for (int i = 0; i < g[node].size(); i++) {\n'
    '            int next = g[node][i];\n'
    '            if (!vis[next]) {\n'
    '                dis[next] = dis[node] + 1;\n'
    '                vis[next] = true;\n'
    '                q.push(next);\n'
    '            }\n'
    '        }\n'
    '    }\n'
    '    //Find answer by use backtracking\n'
    '    if (dis[n] == 0) {\n'
    '        cout << "IMPOSSIBLE";\n'
    '        return 0;\n'
    '    }\n'
    "    cout << dis[n] << '\\n';\n"
    '    vector<int> route;\n'
    '    int now = n;\n'
    '    while (now != 1) {\n'
    '        route.push_back(now);\n'
    '        for (int i = 0; i < g[now].size(); i++) {\n'
    '            int prev = g[now][i];\n'
    '            if (dis[prev] == dis[now] - 1) {\n'
    '                now = prev;\n'
    '                break;\n'
    '            }\n'
    '        }\n'
    '    }\n'
    '    route.push_back(1);\n'
    '    reverse(route.begin(), route.end());\n'
    "    for (int x : route) cout << x << ' ';\n"
    '}\n'
)


@requires_cpp
def test_backtracking_route_and_line_reads_are_drawn_on_the_graph() -> None:
    # CSES 1667: BFS, then walk back from n by `dis`, pushing each vertex onto `route`.
    steps = run_debugger(MESSAGE_ROUTE, stdin_text=ROUTE_INPUT, language="cpp")["steps"]
    check = next(step["visualization"] for step in steps if step["line"] == 33)
    assert check["reading"] == [{"vertex": "5", "text": "dis[n] = 3"}]
    # `dis` labels the vertices but stays listed in Variables (the user's choice).
    assert "dis" not in check["uses"]
    compare = next(step["visualization"] for step in steps if step["line"] == 44)
    assert compare["current"] == "5" and compare["checking"] == {"source": "5", "target": "4"}
    moved = next(step["visualization"] for step in steps if step["line"] == 45)
    assert moved["route"] == {"name": "route", "items": ["5"], "next": "4"}
    final = steps[-1]["visualization"]
    assert final["route"]["items"] == ["1", "4", "5"]
