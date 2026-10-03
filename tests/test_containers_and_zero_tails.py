import shutil

import pytest

from app.cpp_runner import _serialize_cpp_value
from app.cpp_source import classify_type
from app.runner import run_debugger
from app.serializer import serialize_value

requires_cpp = pytest.mark.skipif(
    not shutil.which("g++") or not shutil.which("gdb"),
    reason="C++ toolchain unavailable",
)


def _values(value: dict) -> list:
    return [item.get("value") for item in value["items"]]


def test_python_list_folds_a_long_zero_tail_including_unread_items() -> None:
    value = serialize_value([0, 1, 2, 2] + [0] * 100)

    assert value["fill"] == {"from": 4, "value": {"type": "int", "value": 0}}
    assert value["length"] == 104


def test_short_zero_runs_and_nonzero_unread_items_are_not_folded() -> None:
    assert "fill" not in serialize_value([1, 0, 0, 0])
    assert "fill" not in serialize_value([0] * 60 + [7])


def test_cpp_tail_summary_proves_unread_elements_are_zero() -> None:
    items = "{" + ", ".join(["0", "1", "2"] + ["0"] * 47) + "}..."

    folded = _serialize_cpp_value(f"{items}\n@tail 3 100005", "::dis")
    nonzero_later = _serialize_cpp_value(f"{items}\n@tail 70 100005", "::dis")

    assert folded["fill"]["from"] == 3
    assert folded["length"] == 100005
    assert "fill" not in nonzero_later and nonzero_later["truncated"] is True


def test_deque_output_is_joined_across_buffers() -> None:
    value = _serialize_cpp_value("@queue 3\n{4, 5}\n{6}", "main:q")

    assert value["class_name"] == "queue"
    assert _values(value) == [4, 5, 6]


def test_queue_stack_and_deque_are_extracted_but_other_adaptors_are_not() -> None:
    assert classify_type("std::queue<long long, std::deque<long long> >", 0, {})[0] == "queue"
    assert classify_type("stack<int>", 0, {})[0] == "stack"
    assert classify_type("deque<pair<int,int>>", 0, {})[0] == "deque"
    assert classify_type("stack<int, vector<int>>", 0, {}) is None


@requires_cpp
def test_cpp_bfs_shows_queue_contents_and_folds_the_distance_array() -> None:
    result = run_debugger(
        """#include <bits/stdc++.h>
using namespace std;
int dis[100005];
int main() {
    queue<int> q;
    q.push(1);
    dis[1] = 1;
    q.push(2);
    dis[2] = 2;
    q.pop();
    return 0;
}
""",
        language="cpp",
    )

    assert result["status"] == "completed"
    last = result["steps"][-1]
    assert _values(last["locals"]["q"]) == [2]
    dis = last["globals"]["dis"]
    assert _values(dis)[:3] == [0, 1, 2]
    assert dis["fill"]["from"] == 3 and dis["length"] == 100005


def test_references_print_their_value() -> None:
    assert _serialize_cpp_value("@0x1c941ff658: 2", "main:t") == {"type": "int", "value": 2}


def test_tree_containers_and_heaps_are_parsed() -> None:
    nl = chr(10)
    multiset = _serialize_cpp_value(nl.join(["@multiset 3", "3", "5", "5"]), "main:s")
    mapping = _serialize_cpp_value(nl.join(["@map 2", "{first = 2, second = 7}", "{first = 5, second = 1}"]), "main:m")
    heap = _serialize_cpp_value("@heap" + nl + "{9, 4, 7}", "main:pq")

    assert multiset["class_name"] == "multiset" and _values(multiset) == [3, 5, 5]
    assert mapping["class_name"] == "map"
    assert [(entry["key"]["value"], entry["value"]["value"]) for entry in mapping["entries"]] == [(2, 7), (5, 1)]
    assert heap["class_name"] == "priority_queue" and _values(heap) == [9, 4, 7]


def test_iterators_are_labelled_instead_of_opaque() -> None:
    value = _serialize_cpp_value("{_M_node = 0x1b2c3d4}", "main:it")

    assert value["class_name"] == "iterator"


@requires_cpp
def test_cpp_set_map_and_priority_queue_contents() -> None:
    result = run_debugger(
        """#include <bits/stdc++.h>
using namespace std;
#define int long long
signed main() {
    multiset<int> s = {5, 3, 5};
    map<int, int> freq;
    freq[2]++;
    freq[2]++;
    freq[9]++;
    set<pair<int, int>> seen = {{1, 2}, {0, 5}};
    priority_queue<int> pq;
    pq.push(4);
    pq.push(9);
    return 0;
}
""",
        language="cpp",
    )

    last = result["steps"][-1]["locals"]
    assert _values(last["s"]) == [3, 5, 5]
    assert [(entry["key"]["value"], entry["value"]["value"]) for entry in last["freq"]["entries"]] == [(2, 2), (9, 1)]
    assert [[item["value"] for item in pair["items"]] for pair in last["seen"]["items"]] == [[0, 5], [1, 2]]
    assert _values(last["pq"]) == [9, 4]


@requires_cpp
def test_cpp_matrix_with_rows_larger_than_gdb_value_limit() -> None:
    result = run_debugger(
        "int sp[18][200005];\nint main() {\n    sp[1][2] = 7;\n    return 0;\n}\n",
        language="cpp",
    )

    assert result["status"] == "completed"
    rows = result["steps"][-1]["globals"]["sp"]["items"]
    assert rows[1]["items"][2]["value"] == 7


def test_pointers_into_named_objects_show_the_target() -> None:
    assert _serialize_cpp_value("0x7ff76d13df20 <d1>", "dfs:d")["value"] == "→ d1"
    assert _serialize_cpp_value("(int *) 0x7ff76d13df20 <d1+40>", "dfs:d")["value"] == "→ d1+40"
