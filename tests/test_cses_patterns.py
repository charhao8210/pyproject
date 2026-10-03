"""Patterns from typical CSES solutions that the analyzer and C++ tracer must handle."""
import shutil

import pytest

from app.analyzer import _is_grid, _logical_length
from app.cpp_source import analyze_source
from app.runner import run_debugger

requires_cpp = pytest.mark.skipif(
    not shutil.which("g++") or not shutil.which("gdb"),
    reason="C++ toolchain unavailable",
)


def test_unused_rows_of_a_fixed_size_char_grid_are_ignored() -> None:
    assert _is_grid([".#..", ".#.#", "##..", "", ""])
    assert not _is_grid([".#..", "", "##.."])


def test_array_views_keep_data_stored_past_n() -> None:
    assert _logical_length({"n": 4}, [1, 1, 2, 4, 8, 0, 0]) == 5
    assert _logical_length({"n": 4}, [3, 1, 2, 0, 0, 0]) == 4


def test_declarations_are_recorded_on_the_line_where_they_start() -> None:
    model = analyze_source(
        "int main() {\n"
        "    int a, b = 2;\n"
        "    for (int i = 0; i < 3; ++i) a = i;\n"
        "    vector<pair<int, int>> v;\n"
        "    for (auto [x, y] : v) return x;\n"
        "    return a;\n"
        "}\n"
    )

    assert model.line_declarations[2] == {"a", "b"}
    assert model.line_declarations[3] == {"i"}
    assert model.line_declarations[4] == {"v"}
    assert model.line_declarations[5] == {"x", "y"}
    assert 6 not in model.line_declarations


def test_bfs_graph_view_draws_the_queue_and_distances() -> None:
    result = run_debugger(
        "graph = {1: [2, 3], 2: [1], 3: [1]}\n"
        "dis = [0, 0, 0, 0]\n"
        "vis = [False] * 4\n"
        "q = [1]\n"
        "vis[1] = True\n"
        "while q:\n"
        "    node = q.pop(0)\n"
        "    for v in graph[node]:\n"
        "        if not vis[v]:\n"
        "            vis[v] = True\n"
        "            dis[v] = dis[node] + 1\n"
        "            q.append(v)\n"
    )

    views = [
        step["views"]["graph:graph"]
        for step in result["steps"]
        if step["views"].get("graph:graph", {}).get("frontier", {}) and step["views"]["graph:graph"]["frontier"]["items"]
    ]
    assert views
    view = views[-1]
    assert view["frontier"]["name"] == "q"
    assert view["labels"]["name"] == "dis"
    assert {"q", "dis", "vis", "graph"} <= set(view["uses"])


@requires_cpp
def test_cpp_line_about_to_declare_a_variable_hides_its_garbage() -> None:
    result = run_debugger(
        "#include <bits/stdc++.h>\n"
        "using namespace std;\n"
        "int main() {\n"
        "    int n = 3;\n"
        "    for (int i = 0; i < n; ++i) cout << i;\n"
        "    int done = 1;\n"
        "    return done;\n"
        "}\n",
        language="cpp",
    )

    line_five = next(step for step in result["steps"] if step["line"] == 5)
    line_six = next(step for step in result["steps"] if step["line"] == 6)
    assert "i" not in line_five["locals"]
    assert "done" not in line_six["locals"]


@requires_cpp
def test_auto_view_falls_back_when_the_profile_renderer_never_has_data() -> None:
    result = run_debugger(
        "#include <bits/stdc++.h>\n"
        "using namespace std;\n"
        "long long dp[1000005];\n"
        "int main() {\n"
        "    int n = 3;\n"
        "    dp[0] = 1;\n"
        "    for (int i = 1; i <= n; i++)\n"
        "        for (int d = 1; d <= 6 && d <= i; d++)\n"
        "            dp[i] += dp[i - d];\n"
        "    cout << dp[n];\n"
        "}\n",
        language="cpp",
    )

    last = result["steps"][-1]["visualization"]
    assert last["ready"] is True
    assert last["name"] == "dp"
    assert last["values"] == [1, 1, 2, 4]


def test_union_find_parent_array_is_drawn_as_a_forest() -> None:
    result = run_debugger(
        "p = list(range(5))\n"
        "sz = [1] * 5\n"
        "def find(x):\n"
        "    while p[x] != x:\n"
        "        x = p[x]\n"
        "    return x\n"
        "for a, b in [(0, 1), (2, 3), (1, 3)]:\n"
        "    a, b = find(a), find(b)\n"
        "    if a != b:\n"
        "        p[b] = a\n"
        "        sz[a] += sz[b]\n"
    )

    assert result["algorithm"]["kind"] == "union_find"
    assert result["algorithm"]["views"][0]["id"] == "dsu:p"
    last = result["steps"][-1]["visualization"]
    assert last["layout"] == "forest" and last["directed"] is True
    assert {(edge["source"], edge["target"]) for edge in last["edges"]} == {("1", "0"), ("3", "2"), ("2", "0")}
    assert last["labels"]["name"] == "sz"
    assert {"p", "sz"} <= set(last["uses"])


@requires_cpp
def test_cached_globals_still_see_writes_through_pointer_parameters() -> None:
    result = run_debugger(
        "int a[100];\n"
        "void fill_ones(int *arr, int n) {\n"
        "    for (int i = 0; i < n; i++)\n"
        "        arr[i] = 1;\n"
        "}\n"
        "int main() {\n"
        "    fill_ones(a, 3);\n"
        "    int s = 0;\n"
        "    return s;\n"
        "}\n",
        language="cpp",
    )

    last = result["steps"][-1]["globals"]["a"]
    assert [item["value"] for item in last["items"][:4]] == [1, 1, 1, 0]
    assert last["fill"]["from"] == 3 and last["length"] == 100


CSES_1638 = """#include<bits/stdc++.h>
using namespace std;
#define int long long
const int mod=1e9+7;
int n;
char a[1005][1005];
int dp[1005][1005];
signed main()
{
    cin>>n;
    for(int i=1; i<=n; i++) {
        for(int j=1; j<=n; j++) {
            cin>>a[i][j];
        }
    }
    dp[1][1]=1;
    for(int i=1; i<=n; i++) {
        for(int j=1; j<=n; j++) {
            if(i==1 and j==1) continue;
            if(a[i][j]=='*') {
                dp[i][j]=0;
                continue;
            }
            dp[i][j]=(dp[i-1][j]+dp[i][j-1])%mod;
        }
    }
    cout<<dp[n][n];
}
"""


@requires_cpp
def test_grid_dp_shows_the_map_while_reading_then_the_table_with_walls() -> None:
    result = run_debugger(CSES_1638, language="cpp", stdin_text="4\n....\n.*..\n...*\n*...\n")

    assert result["steps"][-1]["stdout"] == "3"
    views = [step["visualization"] for step in result["steps"] if step["visualization"].get("ready")]
    # 1-indexed: rows and columns 0..4, the same size from the first step to the last.
    assert {(len(view["rows"]), len(view["rows"][0])) for view in views} == {(5, 5)}
    reading = [view for step, view in zip(result["steps"], views) if step["line"] == 13]
    assert reading and all(view["name"] == "a" for view in reading)
    assert any(view["rows"][2][1:] == [".", "*", ".", "."] for view in reading)
    last = views[-1]
    assert last["name"] == "dp"
    assert last["rows"][4] == [0, "*", 1, 3, 3]
    assert {(wall["row"], wall["column"]) for wall in last["walls"]} == {(2, 2), (3, 4), (4, 1)}
    assert {"a", "dp"} <= set(last["uses"])


@requires_cpp
def test_tree_dfs_is_drawn_as_a_graph_with_the_edge_being_checked() -> None:
    result = run_debugger(
        """#include <bits/stdc++.h>
using namespace std;
vector<int> child[100];
int sub[100];
void dfs(int u) {
    for (int v : child[u]) {
        dfs(v);
        sub[u] += sub[v] + 1;
    }
}
int main() {
    child[1].push_back(2);
    child[1].push_back(3);
    child[2].push_back(4);
    dfs(1);
    return 0;
}
""",
        language="cpp",
    )

    assert result["algorithm"]["renderer"] == "graph"
    checking = [step["visualization"]["checking"] for step in result["steps"] if step["visualization"].get("checking")]
    assert {"source": "1", "target": "2"} in checking
    assert {"source": "2", "target": "4"} in checking


def test_strings_get_a_cells_view_with_index_markers() -> None:
    result = run_debugger(
        "s = 'ATTCGG'\n"
        "best = cur = 1\n"
        "for i in range(1, len(s)):\n"
        "    cur = cur + 1 if s[i] == s[i - 1] else 1\n"
        "    best = max(best, cur)\n"
    )

    assert "cells:s" in [view["id"] for view in result["algorithm"]["views"]]
    view = next(step["views"]["cells:s"] for step in result["steps"] if step["line"] == 4)
    assert view["values"][:3] == ["'A'", "'T'", "'T'"] or view["values"][:3] == ["A", "T", "T"]


def test_tree_graphs_get_parents_for_a_top_down_layout_and_labels() -> None:
    result = run_debugger(
        "adj = [[], [2, 3], [1, 4], [1], [2]]\n"
        "sub = [0] * 5\n"
        "def dfs(u, p):\n"
        "    for v in adj[u]:\n"
        "        if v != p:\n"
        "            dfs(v, u)\n"
        "            sub[u] += sub[v] + 1\n"
        "dfs(1, 0)\n"
    )

    view = result["steps"][-1]["views"]["graph:adj"]
    assert view["layout"] == "tree"
    assert view["parents"] == {"2": "1", "3": "1", "4": "2"}
    assert view["labels"]["name"] == "sub"


def test_graph_visited_comes_from_a_team_array_without_vis() -> None:
    result = run_debugger(
        "adj = [[], [2, 3], [1], [1], []]\n"
        "team = [0] * 5\n"
        "team[1] = 1\n"
        "q = [1]\n"
        "while q:\n"
        "    u = q.pop(0)\n"
        "    for v in adj[u]:\n"
        "        if not team[v]:\n"
        "            team[v] = 3 - team[u]\n"
        "            q.append(v)\n"
    )

    view = result["steps"][-1]["views"]["graph:adj"]
    assert set(view["visited"]) == {"1", "2", "3"}


@requires_cpp
def test_auto_label_and_bar_length_follow_what_is_drawn() -> None:
    result = run_debugger(
        "#include <bits/stdc++.h>\nusing namespace std;\nint dp[1000005];\n"
        "int main() {\n    int n = 3, x = 6;\n    dp[0] = 1;\n"
        "    for (int s = 1; s <= x; s++)\n        dp[s] = dp[s - 1] + 1;\n    return 0;\n}\n",
        language="cpp",
    )

    assert result["algorithm"]["auto_renderer"] == "array"
    lengths = {len(step["visualization"]["values"]) for step in result["steps"] if step["visualization"].get("ready")}
    assert lengths == {7}
