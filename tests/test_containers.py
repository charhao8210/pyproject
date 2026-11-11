"""Stack and Queue views (design approved 2026-11-11)."""

import shutil
from pathlib import Path

import pytest

from app.containers import container_kinds, shown_indexes
from app.runner import run_debugger

requires_cpp = pytest.mark.skipif(
    not (shutil.which("g++") and shutil.which("gdb")),
    reason="g++ and gdb are required for C++ tracing tests",
)


def test_containers_are_recognised_by_type_or_by_how_a_list_is_used() -> None:
    cpp = "queue<pair<int, int>> q;\nstd::stack<int> st;\ndeque<int> dq;\npriority_queue<int> pq;\nvector<queue<int>> many;\n"
    assert container_kinds(cpp, "cpp") == {"q": "queue", "st": "stack", "dq": "queue"}
    python = "st = []\nst.append(1)\nst.pop()\nq = [1]\nq.append(2)\nq.pop(0)\na = [3]\na.append(4)\n"
    assert container_kinds(python, "python") == {"st": "stack", "q": "queue"}


def test_long_stacks_show_the_top_ten_and_long_queues_their_ends() -> None:
    assert shown_indexes("stack", 30) == list(range(29, 19, -1))
    assert shown_indexes("queue", 20) == [0, 1, 2, 3, 4, 5, 18, 19]
    assert shown_indexes("queue", 9) == list(range(9))


def test_a_python_stack_is_drawn_top_first_with_pushes_and_reads_marked() -> None:
    code = "st = []\nfor x in [9, 2, 5, 7]:\n    st.append(x)\ntop = st[-1]\nst.pop()\n"
    result = run_debugger(code)
    assert result["algorithm"]["auto_renderer"] == "stack"
    pushed = [step["visualization"] for step in result["steps"] if step["line"] == 3]
    assert [entry["text"] for entry in pushed[-1]["entries"]] == ["7", "5", "2", "9"]
    assert pushed[-1]["added"] == [3]
    reading = next(step["visualization"] for step in result["steps"] if step["line"] == 4)
    assert reading["reading"] == [3]
    popped = next(step["visualization"] for step in result["steps"] if step["line"] == 5)
    assert [entry["text"] for entry in popped["entries"]] == ["5", "2", "9"] and not popped.get("added")


@requires_cpp
def test_bfs_draws_its_queue_above_the_graph() -> None:
    from tests.test_audit_fixes import BFS

    steps = run_debugger(BFS, stdin_text="5 5\n1 2\n1 3\n2 3\n1 4\n4 5\n", language="cpp")["steps"]
    shown = [step["visualization"] for step in steps if step["visualization"].get("container")]
    assert shown and all(view["renderer"] == "graph" and view["container"]["name"] == "q" for view in shown)
    assert "q" in shown[0]["uses"]
    assert any(view["container"].get("added") for view in shown)


def test_the_page_draws_stacks_and_queues() -> None:
    script = (Path(__file__).resolve().parents[1] / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert "stack: renderStackAlgorithm" in script and "queue: renderQueueAlgorithm" in script
    assert "queueCompanion(visualization.container)" in script
