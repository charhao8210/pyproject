"""Algorithm chooser (design approved 2026-11-11): the user picks what the program does before
Run; the code pre-fills each slot's variables, and the chosen algorithm is drawn as picked."""

import shutil

import pytest
from fastapi.testclient import TestClient

from app.chooser import slot_candidates
from app.main import app
from app.runner import run_debugger

PY_BFS = """
n = 4
graph = [[1, 2], [0, 3], [0], [1]]
dist = [-1] * n
best = [0] * n
q = [0]
dist[0] = 0
while q:
    u = q.pop(0)
    for v in graph[u]:
        if dist[v] == -1:
            dist[v] = dist[u] + 1
            best[v] = best[u] + 10
            q.append(v)
"""

PY_SORT = """a = [5, 1, 4]
b = [9, 3, 7, 2]
for i in range(len(b)):
    for j in range(len(b) - 1 - i):
        if b[j] > b[j + 1]:
            b[j], b[j + 1] = b[j + 1], b[j]
"""

CPP_DECLARATIONS = """#include <bits/stdc++.h>
using namespace std;
struct Node { int val; Node *next; };
int n, m;
vector<vector<int>> g;
int dis[100005];
vector<int> adj[100];
vector<string> maze;
int main() {
    vector<int> a(n);
    stack<int> st;
    queue<pair<int, int>> q;
    long long arr[10];
    char grid[5][5];
    Node *head = nullptr;
    priority_queue<int> pq;
    return 0;
}
"""


def test_python_slots_are_filled_from_the_code() -> None:
    slots = slot_candidates(PY_BFS, "python")
    assert slots["graph"][0] == "graph"
    assert slots["queue"][0] == "q"
    assert slots["distance"][0] == "dist" and "best" in slots["distance"]
    assert "graph" not in slots["array"] and "dist" in slots["array"]
    assert slots["node"] == []


def test_python_node_variables_fill_the_linked_list_slot() -> None:
    code = "class Node:\n    def __init__(self, v):\n        self.val = v\n        self.next = None\n\nhead = None\nhead = Node(1)\ncur = head.next\n"
    assert slot_candidates(code, "python")["node"] == ["head", "cur"]


def test_cpp_slots_are_filled_from_declarations() -> None:
    slots = slot_candidates(CPP_DECLARATIONS, "cpp")
    assert slots["graph"][0] == "g" and {"adj", "maze", "grid"} <= set(slots["graph"])
    assert {"a", "dis", "arr"} <= set(slots["array"]) and "g" not in slots["array"]
    assert slots["queue"][0] == "q" and "pq" not in slots["queue"]
    assert slots["stack"][0] == "st"
    assert slots["distance"][0] == "dis"
    assert slots["node"] == ["head"]
    assert not {"n", "m", "main"} & {name for names in slots.values() for name in names}


def test_broken_code_has_no_candidates() -> None:
    assert slot_candidates("def broken(:\n", "python") == {
        "array": [], "graph": [], "queue": [], "stack": [], "node": [], "distance": [],
    }


def test_the_candidates_endpoint() -> None:
    response = TestClient(app).post("/api/candidates", json={"code": PY_SORT, "language": "python"})
    assert response.status_code == 200
    assert response.json()["slots"]["array"] == ["a", "b"]


def _ready(result):
    return [step["visualization"] for step in result["steps"] if step["visualization"].get("ready")]


def test_a_chosen_array_is_drawn_whatever_the_guess_would_be() -> None:
    result = run_debugger(PY_SORT, choice={"algorithm": "sorting", "variables": {"array": "a"}})
    views = _ready(result)
    assert views and all(view["renderer"] == "array" and view["name"] == "a" for view in views)
    assert result["algorithm"]["choice"] == {"algorithm": "sorting", "label": "Sorting", "variables": ["a"]}
    assert result["algorithm"]["name"] == "Sorting"


def test_bfs_draws_the_chosen_graph_with_the_chosen_queue_above() -> None:
    result = run_debugger(PY_BFS, choice={"algorithm": "bfs", "variables": {"graph": "graph", "queue": "q"}})
    views = _ready(result)
    assert views and all(view["renderer"] == "graph" for view in views)
    assert any((view.get("container") or {}).get("name") == "q" for view in views)
    assert result["algorithm"]["choice"]["variables"] == ["graph", "q"]


def test_dfs_without_a_stack_draws_the_graph_alone() -> None:
    result = run_debugger(PY_BFS, choice={"algorithm": "dfs", "variables": {"graph": "graph", "stack": ""}})
    views = _ready(result)
    assert views and not any(view.get("container") for view in views)


def test_shortest_path_labels_vertices_with_the_chosen_array() -> None:
    result = run_debugger(PY_BFS, choice={"algorithm": "shortest_path", "variables": {"graph": "graph", "distance": "best"}})
    labelled = [view for view in _ready(result) if view.get("labels")]
    assert labelled and all(view["labels"]["name"] == "best" for view in labelled)


def test_a_chosen_variable_without_data_says_so_instead_of_guessing() -> None:
    result = run_debugger(PY_SORT, choice={"algorithm": "stack", "variables": {"stack": "zz"}})
    assert all(step["visualization"].get("missing") == "zz" and not step["visualization"].get("ready") for step in result["steps"])
    empty = run_debugger(PY_SORT, choice={"algorithm": "linked_list", "variables": {"node": ""}})
    assert all(step["visualization"].get("missing") == "" for step in empty["steps"])


def test_recursion_choice_draws_the_recursion_tree() -> None:
    code = "def f(n):\n    if n < 2:\n        return n\n    return f(n - 1) + f(n - 2)\n\nx = f(3)\n"
    result = run_debugger(code, choice={"algorithm": "recursion", "variables": {}})
    assert {view["renderer"] for view in _ready(result)} == {"recursion_tree"}


def test_other_keeps_the_guess() -> None:
    guessed = run_debugger(PY_SORT)
    other = run_debugger(PY_SORT, choice={"algorithm": "other", "variables": {}})
    assert [step["visualization"] for step in other["steps"]] == [step["visualization"] for step in guessed["steps"]]
    assert "choice" not in other["algorithm"]


def test_the_debug_endpoint_takes_a_choice() -> None:
    response = TestClient(app).post(
        "/api/debug",
        json={"code": PY_SORT, "language": "python", "choice": {"algorithm": "sorting", "variables": {"array": "a"}}},
    )
    assert response.status_code == 200
    assert response.json()["algorithm"]["choice"]["label"] == "Sorting"
    bad = TestClient(app).post("/api/debug", json={"code": PY_SORT, "choice": {"algorithm": "nope"}})
    assert bad.status_code == 422


requires_cpp = pytest.mark.skipif(
    not (shutil.which("g++") and shutil.which("gdb")),
    reason="g++ and gdb are required for C++ tracing tests",
)


@requires_cpp
def test_a_cpp_choice_is_drawn() -> None:
    code = """#include <bits/stdc++.h>
using namespace std;
int main() {
    vector<int> a = {5, 1, 4};
    vector<int> b = {9, 3, 7};
    sort(b.begin(), b.end());
    return 0;
}
"""
    result = run_debugger(code, language="cpp", choice={"algorithm": "array", "variables": {"array": "a"}})
    views = _ready(result)
    assert views and all(view["name"] == "a" for view in views)


def test_the_page_has_the_chooser() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    page = (root / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    script = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'id="algorithm-chooser"' in page and 'id="chooser-run-button"' in page
    assert "const ALGORITHM_CHOICES" in script and '"/api/candidates"' in script
    assert "choice: state.choice" in script and "Run as " in script
    # A DFS stack is drawn above the graph like a BFS queue.
    assert 'view.renderer === "stack" ? stackBody(view) : queueBody(view)' in script
    assert '"picked before Run"' in (root / "app" / "static" / "terms.js").read_text(encoding="utf-8")
    assert "Run as" in (root / "app" / "templates" / "help.html").read_text(encoding="utf-8")
