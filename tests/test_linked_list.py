"""Linked List view (design approved 2026-11-11, mockup views-dark.png)."""

from pathlib import Path

from app.runner import run_debugger
from app.serializer import serialize_value

NODE = "class Node:\n    def __init__(self, val):\n        self.val = val\n        self.next = None\n\n"


def _texts(row):
    return [item.get("text") for item in row["items"]]


def _pointers(row):
    return {name: item["text"] for item in row["items"] if "id" in item for name in item["pointers"]}


def test_a_whole_chain_is_serialized_past_the_depth_limit() -> None:
    class Node:
        def __init__(self, val, nxt=None):
            self.val = val
            self.next = nxt

    head = None
    for value in range(12, 0, -1):
        head = Node(value, head)
    node = serialize_value(head)
    count = 0
    while node.get("type") == "dict":
        assert not node.get("truncated")
        count += 1
        node = next(entry["value"] for entry in node["entries"] if entry["key"]["value"] == "next")
    assert count == 12 and node["type"] == "none"


def test_a_list_is_drawn_as_nodes_with_pointer_labels() -> None:
    code = NODE + "head = Node(3)\nhead.next = Node(8)\nhead.next.next = Node(1)\ncur = head\nwhile cur:\n    cur = cur.next\n"
    result = run_debugger(code)
    assert result["algorithm"]["auto_renderer"] == "linked_list"
    views = [step["visualization"] for step in result["steps"] if step["visualization"].get("ready")]
    full = [view for view in views if len(view["rows"]) == 1 and _texts(view["rows"][0]) == ["3", "8", "1"]]
    assert full and full[0]["rows"][0]["end"] == {"kind": "none"}
    assert any(_pointers(view["rows"][0]) == {"head": "3", "cur": "8"} for view in full)
    assert any({"head", "cur"} <= set(view["uses"]) for view in full)
    # A node is New on the constructor line that gives it its `next` field, once per node.
    created = [step for step in result["steps"] if step["visualization"].get("added")]
    assert len(created) == 3 and all(step["function"] == "__init__" for step in created)
    reading = next(step["visualization"] for step in result["steps"] if step["line"] == 11)
    assert reading["reading"]


def test_a_long_list_folds_its_middle_but_keeps_pointed_nodes() -> None:
    code = NODE + (
        "head = None\nfor v in range(20, 0, -1):\n    node = Node(v)\n    node.next = head\n    head = node\n"
        "mid = head\nfor _ in range(10):\n    mid = mid.next\ndone = True\n"
    )
    view = run_debugger(code)["steps"][-1]["visualization"]
    row = view["rows"][0]
    assert _texts(row) == ["1", "2", "3", "4", "5", "6", None, "11", None, "19", "20"]
    assert [item.get("gap") for item in row["items"] if "gap" in item] == [4, 7]
    assert _pointers(row) == {"head": "1", "node": "1", "mid": "11"} and view["size"] == 20


def test_a_cycle_ends_in_a_line_back() -> None:
    code = NODE + "a = Node(1)\na.next = Node(2)\na.next.next = Node(3)\na.next.next.next = a\ndone = True\n"
    view = run_debugger(code)["steps"][-1]["visualization"]
    row = view["rows"][0]
    assert _texts(row) == ["1", "2", "3"]
    assert row["end"] == {"kind": "cycle", "to": row["items"][0]["id"]}


def test_reversing_a_list_draws_one_row_per_chain() -> None:
    code = NODE + (
        "head = Node(1)\nhead.next = Node(2)\nhead.next.next = Node(3)\nhead.next.next.next = Node(4)\n"
        "prev = None\ncur = head\nwhile cur:\n    nxt = cur.next\n    cur.next = prev\n    prev = cur\n    cur = nxt\n"
    )
    steps = run_debugger(code)["steps"]
    shapes = [sorted(map(_texts, step["visualization"]["rows"])) for step in steps if step["visualization"].get("ready")]
    assert [["2", "1"], ["3", "4"]] in shapes
    assert [["4", "3", "2", "1"]] in shapes


def test_the_page_draws_linked_lists() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert "linked_list: renderLinkedListAlgorithm" in script
    assert '"Linked list"' in (root / "app" / "static" / "terms.js").read_text(encoding="utf-8")


def test_a_list_longer_than_what_is_read_ends_in_more() -> None:
    code = NODE + "head = None\nfor v in range(70):\n    node = Node(v)\n    node.next = head\n    head = node\ndone = True\n"
    result = run_debugger(code)
    assert [view["id"] for view in result["algorithm"]["views"] if view["renderer"] == "linked_list"] == ["linked_list:node"]
    view = result["steps"][-1]["visualization"]
    assert view["rows"][0]["end"] == {"kind": "more"} and view["partial"]
    assert "…" not in _texts(view["rows"][0])
