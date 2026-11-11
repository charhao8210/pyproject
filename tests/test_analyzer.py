from app.analyzer import _is_adjacency, analyze_execution
from app.runner import run_debugger


def _int(value: int) -> dict:
    return {"type": "int", "value": value}


def _list(items: list[dict], object_id: int) -> dict:
    return {"type": "list", "object_id": object_id, "items": items}


def test_grid_traversal_uses_grid_renderer() -> None:
    source = """\
import sys

def main():
    data = sys.stdin.read().split()
    n, m = int(data[0]), int(data[1])
    a = data[2:2 + n]
    vis = [[False] * m for _ in range(n)]
    dirs = ((1, 0), (-1, 0), (0, 1), (0, -1))
    stack = [(0, 0)]
    while stack:
        c, r = stack.pop()
        if vis[c][r]:
            continue
        vis[c][r] = True
        for dc, dr in dirs:
            wc, wr = c + dc, r + dr
            if 0 <= wc < n and 0 <= wr < m and not vis[wc][wr] and a[wc][wr] != '#':
                stack.append((wc, wr))

main()
"""
    result = run_debugger(source, stdin_text="2 3\n...\n.#.\n")

    assert result["algorithm"]["kind"] == "grid_traversal"
    assert result["algorithm"]["renderer"] == "grid"
    ready = [step["visualization"] for step in result["steps"] if step["visualization"].get("ready")]
    assert ready
    assert ready[-1]["rows"] == [[".", ".", "."], [".", "#", "."]]
    assert result["steps"][-1]["visualization"]["ready"] is True
    assert result["steps"][-1]["visualization"]["carried"] is True
    assert result["steps"][-1]["visualization"]["uses"] == []


def test_grid_visualization_lists_the_variables_it_draws() -> None:
    source = """\
a = ["...", ".#."]
vis = [[False] * 3 for _ in range(2)]
stack = [(0, 0)]
c, r = stack.pop()
vis[c][r] = True
"""
    result = run_debugger(source)

    last = result["steps"][-1]["visualization"]
    assert last["renderer"] == "grid"
    assert set(last["uses"]) == {"a", "vis", "stack", "c", "r"}



def test_list_based_adjacency_uses_graph_renderer() -> None:
    source = """\
import sys

data = sys.stdin.buffer.read().split()
n = int(data[0])
g = [[] for _ in range(n + 1)]
index = 1
for _ in range(n - 1):
    a, b = int(data[index]), int(data[index + 1])
    index += 2
    g[a].append(b)
    g[b].append(a)
par = [0] * (n + 1)
stack = [1]
par[1] = -1
while stack:
    node = stack.pop()
    for neighbor in g[node]:
        if neighbor != par[node]:
            par[neighbor] = node
            stack.append(neighbor)
"""
    result = run_debugger(source, stdin_text="5\n1 2\n1 3\n3 4\n3 5\n")

    assert result["status"] == "completed"
    assert result["algorithm"]["kind"] == "dfs"
    assert result["algorithm"]["renderer"] == "graph"
    ready = [step["visualization"] for step in result["steps"] if step["visualization"].get("ready")]
    assert ready
    assert set(ready[-1]["nodes"]) == {"1", "2", "3", "4", "5"}



def test_adjacency_detection_rejects_flag_and_value_tables() -> None:
    assert _is_adjacency([[2], [0, 2], [1]])
    assert _is_adjacency([[], [2, 3], [1], [1]])
    assert not _is_adjacency([[True, False], [False, True]])
    assert not _is_adjacency([[5, 9], [12, 40]])
    assert not _is_adjacency([[".", "#"], ["#", "."]])


def test_boolean_visited_array_marks_node_indexes() -> None:
    graph = _list([_list([], 2), _list([_int(2)], 3), _list([_int(1)], 4)], 1)
    visited = _list(
        [{"type": "bool", "value": False}, {"type": "bool", "value": True}, {"type": "bool", "value": False}],
        5,
    )
    steps = [{"event": "line", "line": 3, "locals": {"graph": graph, "visited": visited, "u": _int(1)}}]

    analyze_execution("graph = visited = u = None\nwhile u:\n    pass\n", steps)

    view = steps[0]["visualization"]
    assert view["renderer"] == "graph"
    assert view["visited"] == ["1"]
    assert view["current"] == "1"
