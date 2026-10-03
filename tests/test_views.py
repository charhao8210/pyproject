import shutil

import pytest

from app.cpp_runner import _parse_stack
from app.runner import run_debugger


requires_cpp = pytest.mark.skipif(
    not shutil.which("g++") or not shutil.which("gdb"),
    reason="C++ toolchain unavailable",
)

PYTHON_HANOI = """\
def hanoi(n, a, b, c):
    if n == 1:
        return 1
    moves = hanoi(n - 1, a, c, b)
    moves += hanoi(1, a, b, c)
    moves += hanoi(n - 1, b, a, c)
    return moves

total = hanoi(2, 'A', 'B', 'C')
"""


def _view_ids(result: dict) -> list[str]:
    return [view["id"] for view in result["algorithm"]["views"]]


def test_catalog_offers_every_view_that_fits_the_data() -> None:
    source = """\
grid = [[0, 1], [1, 0]]
nums = [3, 1, 2]
names = ["b", "a"]
adj = [[1], [0]]
"""
    result = run_debugger(source)

    ids = _view_ids(result)
    assert {"grid:grid", "array:nums", "cells:nums", "cells:names", "graph:adj", "execution"} <= set(ids)
    assert "array:names" not in ids
    last = result["steps"][-1]
    assert set(last["views"]) == set(ids)
    assert last["views"]["cells:names"]["values"] == ["'b'", "'a'"]


def test_chosen_variable_is_drawn_even_when_auto_prefers_another() -> None:
    source = """\
a = [1, 2, 3]
b = [9, 8, 7]
for i in range(3):
    b[i] = a[i]
"""
    result = run_debugger(source)

    views = [step["views"]["array:b"] for step in result["steps"] if step["views"]["array:b"].get("ready")]
    assert views[-1]["name"] == "b"
    assert views[-1]["values"] == [1, 2, 3]


def test_changed_entries_are_marked_written_and_index_markers_are_reads() -> None:
    source = """\
arr = [5, 6, 7]
for i in range(3):
    arr[i] = 0
"""
    result = run_debugger(source)

    written = [
        (step["views"]["cells:arr"]["written"], step["views"]["cells:arr"]["markers"])
        for step in result["steps"]
        if step["views"]["cells:arr"].get("written")
    ]
    assert [indexes for indexes, _ in written] == [[0], [1], [2]]
    assert all(any(marker["label"] == "i" for marker in markers) for _, markers in written)


def test_python_recursion_tree_records_every_call_with_arguments_and_results() -> None:
    result = run_debugger(PYTHON_HANOI)

    assert "recursion_tree" in _view_ids(result)
    nodes = result["algorithm"]["recursion_tree"]["nodes"]
    assert [node["label"] for node in nodes] == [
        "<module>",
        "hanoi(2,'A','B','C')",
        "hanoi(1,'A','C','B')",
        "hanoi(1,'A','B','C')",
        "hanoi(1,'B','A','C')",
    ]
    assert [node["parent"] for node in nodes] == [None, 0, 1, 1, 1]
    assert nodes[1]["title"] == "hanoi(n=2, a='A', b='B', c='C')"
    assert nodes[1]["return_value"] == "3"
    running = [step["views"]["recursion_tree"] for step in result["steps"]]
    assert {view["current"] for view in running} == {0, 1, 2, 3, 4}
    assert next(view for view in running if view["current"] == 1)["uses"] == ["n", "a", "b", "c"]


def test_sibling_calls_on_the_same_line_become_separate_nodes() -> None:
    source = """\
def fib(n):
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)

x = fib(3)
"""
    result = run_debugger(source)

    labels = [node["label"] for node in result["algorithm"]["recursion_tree"]["nodes"]]
    assert labels == ["<module>", "fib(3)", "fib(2)", "fib(1)", "fib(0)", "fib(1)"]


def test_gdb_backtrace_keeps_call_arguments() -> None:
    text = (
        "#0  hanoi (n=1, a=49 '1', b=51 '3', c=50 '2') at program.cpp:12\n"
        "#1  0x00007ff6 in hanoi (n=2, a=49 '1', b=50 '2', c=51 '3') at program.cpp:16\n"
        "#2  0x00007ff6 in main () at program.cpp:26\n"
    )

    frames = _parse_stack(text)

    assert [frame["function"] for frame in frames] == ["main", "hanoi", "hanoi"]
    assert frames[-1] == {"function": "hanoi", "line": 12, "args": "n=1, a=49 '1', b=51 '3', c=50 '2'"}


@requires_cpp
def test_cpp_recursion_tree_labels_calls_with_char_arguments() -> None:
    source = """\
#include <iostream>
using namespace std;
void hanoi(int n, char a, char b, char c) {
    if (n == 1) {
        cout << a << ' ' << c << endl;
        return;
    }
    hanoi(n - 1, a, c, b);
    hanoi(1, a, b, c);
    hanoi(n - 1, b, a, c);
}
int main() {
    hanoi(2, '1', '2', '3');
}
"""
    result = run_debugger(source, language="cpp")

    labels = [node["label"] for node in result["algorithm"]["recursion_tree"]["nodes"]]
    assert labels == [
        "main()",
        "hanoi(2,'1','2','3')",
        "hanoi(1,'1','3','2')",
        "hanoi(1,'1','2','3')",
        "hanoi(1,'2','1','3')",
    ]
