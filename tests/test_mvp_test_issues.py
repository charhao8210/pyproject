"""Fixes for the issues found while trying the `mvp` branch (mvp-test-issues.md, 2026-11-17)."""

import shutil

import pytest
from fastapi.testclient import TestClient

from app import cpp_runner
from app.chooser import slot_candidates
from app.main import app
from app.runner import run_debugger
from app.tracer import trace_code
from app.validator import SourceValidationError, validate_source

requires_cpp = pytest.mark.skipif(
    not shutil.which("g++") or not shutil.which("gdb"),
    reason="g++ and gdb are required",
)

NEIGHBOURS = """n, m, k=map(int, input().split())
g=[[] for _ in range(n+1)]
for _ in range(m):
    a, b= map(int, input().split())
    g[a]+=[b]
    g[b]+=[a]
f1=set(g[k])
print(len(f1))
"""
NEIGHBOURS_INPUT = "3 2 1\n1 2\n1 3\n"


def test_a_long_program_runs_on_past_the_recorded_steps() -> None:
    result = trace_code("t = 0\nfor i in range(100):\n    t += i\nprint(t)\n", max_steps=1000, max_recorded=50)

    assert result["status"] == "completed"
    assert len(result["steps"]) == 50
    assert result["total_steps"] > 200
    assert result["steps"][-1]["event"] != "stopped"


def test_a_program_past_both_limits_is_a_step_limit_without_a_hidden_terminal_step() -> None:
    result = trace_code("while True:\n    pass\n", max_steps=500, max_recorded=50)

    assert result["status"] == "step_limit"
    assert len(result["steps"]) == 50
    assert result["total_steps"] == 499


@pytest.mark.parametrize(
    "code, output",
    [
        ("from collections import deque\nq = deque([1])\nq.append(2)\nprint(q.popleft())\n", "1\n"),
        ("import heapq\nh = [3, 1, 2]\nheapq.heapify(h)\nprint(h[0])\n", "1\n"),
        ("import math\nprint(math.sqrt(16))\n", "4.0\n"),
        ("from bisect import bisect_left\nprint(bisect_left([1, 3, 5], 3))\n", "1\n"),
        ("import sys\nsys.setrecursionlimit(10000)\nprint(1)\n", "1\n"),
        ("print(1)\nexit()\nprint(2)\n", "1\n"),
        ("import sys\ndef stop():\n    sys.exit(0)\nprint(1)\nstop()\nprint(2)\n", "1\n"),
    ],
)
def test_contest_modules_and_exit_work(code: str, output: str) -> None:
    result = run_debugger(code)

    assert result["status"] == "completed", result["error"]
    assert result["steps"][-1]["stdout"] == output
    assert not any(step.get("exception") for step in result["steps"])


def test_a_deque_is_a_list_and_other_modules_stay_blocked() -> None:
    result = trace_code("from collections import deque\nq = deque([4, 5])\nx = 1\n")
    assert result["steps"][-1]["locals"]["q"]["type"] == "list"
    assert result["steps"][-1]["locals"]["q"]["class_name"] == "deque"

    for code in ("import os\n", "from math import sys\n", "from collections import abc\n"):
        with pytest.raises(SourceValidationError):
            validate_source(code)
    assert run_debugger("import heapq\nheapq._heapify_max([1])\n")["status"] == "exception"


def test_wrong_test_data_gets_a_hint() -> None:
    for stdin in ("5 7\n", ""):
        exception = run_debugger(NEIGHBOURS, stdin_text=stdin)["steps"][-1]["exception"]
        assert "Test data" in exception["hint"]
    # A ValueError that has nothing to do with input gets none.
    assert "hint" not in run_debugger("int('x')\n")["steps"][-1]["exception"]


def test_code_in_the_other_language_gets_a_hint() -> None:
    client = TestClient(app)
    python_as_cpp = client.post("/api/debug", json={"code": NEIGHBOURS, "language": "cpp"})
    cpp_as_python = client.post("/api/debug", json={"code": "#include <iostream>\nint main() { std::cout << 1; }\n"})

    assert cpp_as_python.status_code == 422
    assert "C++，語言是不是選錯了" in cpp_as_python.json()["detail"]["message"]
    if shutil.which("g++") and shutil.which("gdb"):
        assert "Python，語言是不是選錯了" in python_as_cpp.json()["detail"]["message"]


def test_the_array_slot_offers_sets_and_lists_of_lists() -> None:
    assert slot_candidates(NEIGHBOURS, "python")["array"] == ["f1", "g"]
    cpp = "#include <bits/stdc++.h>\nusing namespace std;\nset<int> s;\nint main() { vector<vector<int>> g(2); }\n"
    assert slot_candidates(cpp, "cpp")["array"] == ["s", "g"]


def test_a_chosen_graph_says_from_which_step_it_has_data() -> None:
    steps = run_debugger(
        NEIGHBOURS,
        stdin_text=NEIGHBOURS_INPUT,
        choice={"algorithm": "bfs", "variables": {"graph": "g"}},
    )["steps"]
    first = next(step["step"] for step in steps if step["visualization"].get("ready"))

    assert first > 0
    assert all(step["visualization"]["waiting"] == "g" for step in steps[:first])
    assert all(step["visualization"]["first_step"] == first for step in steps[:first])
    assert "waiting" not in steps[first]["visualization"]


@requires_cpp
def test_a_line_gdb_refuses_does_not_stop_the_other_breakpoints(monkeypatch) -> None:
    # Newer GDBs refuse `break` on a global declaration ("No compiled code for line 3"); a
    # line past the end stands in for it here, since GDB 10 slides such breakpoints instead.
    real = cpp_runner._candidate_lines
    monkeypatch.setattr(cpp_runner, "_candidate_lines", lambda source: [999, *real(source)])
    result = run_debugger(
        "#include <iostream>\nint g = 0;\nint main() {\n  g = 3;\n  std::cout << g;\n}\n",
        language="cpp",
    )

    assert result["status"] == "completed"
    assert [step["line"] for step in result["steps"]] == [4, 5]


@requires_cpp
def test_a_picked_map_fills_cell_by_cell_while_it_is_read() -> None:
    # C++ rows lose their unwritten tail, so a half-read row was shorter than the others and
    # the picked grid fell back to the last fully read state (user report, 2026-11-17).
    code = (
        "#include <bits/stdc++.h>\nusing namespace std;\nint n, m;\nchar a[10][10];\n"
        "int main() {\n  cin >> n >> m;\n  for (int i = 0; i < n; i++)\n"
        "    for (int j = 0; j < m; j++)\n      cin >> a[i][j];\n}\n"
    )
    steps = run_debugger(
        code,
        stdin_text="2 3\n#.#\n.A.\n",
        language="cpp",
        choice={"algorithm": "bfs", "variables": {"graph": "a"}},
    )["steps"]
    # The first read has no earlier grid to compare with, and the last stop has no later one
    # to show its effect from.
    reads = [step["visualization"] for step in steps if step["line"] == 9][1:-1]

    assert all(view["ready"] and not view.get("carried") for view in reads)
    assert [view["written"] for view in reads] == [[{"row": r, "column": c}] for r in range(2) for c in range(3)][1:-1]


@requires_cpp
def test_a_cpp_string_array_maze_is_read() -> None:
    code = """#include <bits/stdc++.h>
using namespace std;
string s[5];
int main() {
    for (int i = 0; i < 2; i++) cin >> s[i];
    return 0;
}
"""
    result = run_debugger(code, stdin_text="#.#\n...\n", language="cpp")
    items = result["steps"][-1]["globals"]["s"]["items"]
    assert [item.get("value") for item in items[:2]] == ["#.#", "..."]


def test_a_grid_marks_the_cell_the_code_subscripts_whatever_the_names() -> None:
    # User's choice 2026-11-18: `a[rr][cc]` makes rr, cc the current cell, in the code's order.
    code = "a = [[0, 0, 0], [0, 0, 0]]\nr, c = 9, 9\nfor rr in range(2):\n    for cc in range(3):\n        a[rr][cc] = 1\nr, c = 0, 2\na[r][c] = 5\n"
    steps = run_debugger(code)["steps"]
    views = [step["views"]["grid:a"] for step in steps if step["views"].get("grid:a", {}).get("ready")]
    assert any({"row": 1, "column": 2, "role": "current"} in view["active"] for view in views)
    assert any("rr,cc = (1, 2)" in view["coordinates"] for view in views)
    # `c, r` used to mean (row c, column r); the code says a[r][c].
    last = views[-1]
    assert {"row": 0, "column": 2, "role": "current"} in last["active"] and "r,c = (0, 2)" in last["coordinates"]


@requires_cpp
def test_the_current_cell_is_the_one_the_line_writes_not_the_next() -> None:
    # User report 2026-11-19: C++ runs `cc++` before the next stop, so Current was one cell ahead.
    code = """#include <bits/stdc++.h>
using namespace std;
int main() {
    int H, W, N;
    cin >> H >> W >> N;
    vector<vector<int>> a(H, vector<int>(W, 0));
    for (int k = 0; k < N; k++) {
        int r, c, t, num;
        cin >> r >> c >> t >> num;
        for (int rr = r - t; rr <= r + t; rr++) {
            for (int cc = c - t; cc <= c + t; cc++) {
                if (0 <= rr && rr < H && 0 <= cc && cc < W && abs(rr - r) + abs(cc - c) <= t) {
                    a[rr][cc] += num;
                }
            }
        }
    }
}
"""
    steps = run_debugger(code, stdin_text="3 3 1\n1 1 1 2\n", language="cpp")["steps"]
    views = [step["views"]["grid:a"] for step in steps if step["line"] == 13]
    written = [view["written"][0] for view in views if view.get("written")]
    assert len(written) == 5
    for view in views:
        if view.get("written"):
            cell = view["written"][0]
            assert {**cell, "role": "current"} in view["active"]
            assert f"rr,cc = ({cell['row']}, {cell['column']})" in view["coordinates"]


def test_a_cell_moved_over_two_lines_stays_put_until_both_have_run() -> None:
    # User report 2026-11-19: `c = ma[0]` drew Current at (new c, old r), a cell never visited.
    code = """n, m = map(int, input().split())
v = [[int(x) for x in input().split()] for _ in range(n)]
c, r = map(int, input().split())
ma = [1, 1]
v[c][r] = 0
c = ma[0]
r = ma[1]
v[c][r] = 0
"""
    steps = run_debugger(code, stdin_text="3 3\n1 2 3\n4 5 6\n7 8 9\n2 0\n", language="python")["steps"]

    def current(line: int) -> dict:
        view = next(step["views"]["grid:v"] for step in steps if step["line"] == line)
        return next(cell for cell in view["active"] if cell["role"] == "current")

    assert (current(6)["row"], current(6)["column"]) == (2, 0)
    assert (current(7)["row"], current(7)["column"]) == (1, 1)
