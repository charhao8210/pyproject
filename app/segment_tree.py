"""Recursive segment trees: `tree[id*2]` / `tree[id*2+1]` children over a range `[l, r]`.

`detect` finds the tree array, the node-id parameter and the range parameters in the source;
`layout` places every node once per trace (its range comes from the first call on the root);
`model` is one step's view: node values, the running node, the call path, the nodes the line
reads, and the original array under the leaves.
"""

from __future__ import annotations

import re
from typing import Any

from .usage import _integer, _substitute

LOWER_NAMES = ("l", "lo", "tl", "s", "start", "nl", "left", "L", "b", "lx", "low")
UPPER_NAMES = ("r", "hi", "tr", "e", "end", "nr", "right", "R", "rx", "high")
MAX_LEAVES = 32
TRUNCATED_DEPTH = 5  # levels drawn when the tree has more leaves than fit

_CHILD = r"(?:{x}\s*\*\s*2|2\s*\*\s*{x}|\(?\s*{x}\s*<<\s*1\s*\)?)"


def detect(source: str, language: str) -> dict[str, Any] | None:
    code = _strip(source, language)
    for match in re.finditer(r"\b([A-Za-z_]\w*)\s*\[\s*(?:([A-Za-z_]\w*)\s*\*\s*2|2\s*\*\s*([A-Za-z_]\w*)|\(?\s*([A-Za-z_]\w*)\s*<<\s*1)", code):
        array = match.group(1)
        node = match.group(2) or match.group(3) or match.group(4)
        child = _CHILD.format(x=re.escape(node))
        index = rf"\b{re.escape(array)}\s*\[\s*"
        has_right = re.search(rf"{index}{child}\s*(?:\+\s*1|\|\s*1)\s*\]", code)
        has_left = re.search(rf"{index}{child}\s*\]", code)
        zero_based = re.search(rf"{index}{child}\s*\+\s*2\s*\]", code)
        if not (has_right and (has_left or zero_based)):
            continue
        functions, lower, upper = _range_functions(code, language, node)
        if not functions:
            continue
        leaf = re.search(
            rf"\b{re.escape(array)}\s*\[\s*{re.escape(node)}\s*\]\s*=\s*([A-Za-z_]\w*)\s*\[\s*{re.escape(lower)}\s*\]", code
        )
        return {
            "array": array,
            "node": node,
            "lower": lower,
            "upper": upper,
            "functions": sorted(functions),
            "root": 0 if zero_based and not has_left else 1,
            "base": leaf.group(1) if leaf else None,
        }
    return None


def _strip(source: str, language: str) -> str:
    if language == "cpp":
        from .cpp_source import strip_code

        return strip_code(source)
    return "\n".join(line.split("#", 1)[0] for line in source.split("\n"))


def _range_functions(code: str, language: str, node: str) -> tuple[set[str], str, str]:
    """Functions taking the node id plus a range, and the names of the range bounds."""
    pattern = r"\bdef\s+([A-Za-z_]\w*)\s*\(([^()]*)\)\s*:" if language != "cpp" else r"\b([A-Za-z_]\w*)\s*\(([^()]*)\)\s*(?:const\s*)?\{"
    functions: set[str] = set()
    bounds: tuple[str, str] | None = None
    for match in re.finditer(pattern, code):
        params = [re.findall(r"[A-Za-z_]\w*", part.split("=", 1)[0])[-1:] for part in match.group(2).split(",")]
        names = [found[0] for found in params if found]
        if node not in names:
            continue
        lower = next((name for name in LOWER_NAMES if name in names and name != node), None)
        upper = next((name for name in UPPER_NAMES if name in names and name != node), None)
        if lower and upper:
            functions.add(match.group(1))
            bounds = bounds or (lower, upper)
    return functions, *(bounds or ("", ""))


def _function_name(step: dict[str, Any]) -> str:
    # C++ frames may read `build(long long, ...)`; Python ones are bare names.
    return str(step.get("function") or "").split("(", 1)[0].strip()


def layout(spec: dict[str, Any], steps: list[dict[str, Any]], scopes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Every node's id, range, depth and column, from the first call on the root."""
    root = spec["root"]
    for step, scope in zip(steps, scopes):
        if _function_name(step) not in spec["functions"]:
            continue
        node, low, high = (scope.get(spec[key]) for key in ("node", "lower", "upper"))
        if node == root and _is_int(low) and _is_int(high) and low <= high:
            break
    else:
        return None
    leaves = high - low + 1
    max_depth = None if leaves <= MAX_LEAVES else TRUNCATED_DEPTH - 1
    nodes: list[dict[str, Any]] = []

    def place(node_id: int, l: int, r: int, depth: int) -> None:
        entry = {"id": node_id, "l": l, "r": r, "depth": depth}
        nodes.append(entry)
        if l == r or depth == max_depth:
            return
        mid = (l + r) // 2
        left = node_id * 2 + 1 if root == 0 else node_id * 2
        place(left, l, mid, depth + 1)
        place(left + 1, mid + 1, r, depth + 1)

    place(root, low, high, 0)
    # Columns: the bottom nodes left to right, each parent centred over its children.
    bottom = [entry for entry in nodes if entry["l"] == entry["r"] or entry["depth"] == max_depth]
    column = {entry["id"]: float(position) for position, entry in enumerate(bottom)}
    for entry in sorted(nodes, key=lambda item: -item["depth"]):
        if entry["id"] in column:
            continue
        left = entry["id"] * 2 + 1 if root == 0 else entry["id"] * 2
        column[entry["id"]] = (column[left] + column[left + 1]) / 2
    for entry in nodes:
        entry["x"] = column[entry["id"]]
    return {
        "nodes": nodes,
        "columns": len(bottom),
        "depth": max(entry["depth"] for entry in nodes) + 1,
        "low": low,
        "high": high,
        "truncated": max_depth is not None,
        "root": root,
    }


def call_paths(spec: dict[str, Any], steps: list[dict[str, Any]], scopes: list[dict[str, Any]]) -> list[list[int]]:
    """For each step, the node ids of the tree calls on the stack, root first."""
    on_stack: dict[int, int] = {}
    paths: list[list[int]] = []
    for step, scope in zip(steps, scopes):
        depth = int(step.get("depth", len(step.get("stack") or [])))
        for stale in [key for key in on_stack if key >= depth]:
            del on_stack[stale]
        node = scope.get(spec["node"])
        if _function_name(step) in spec["functions"] and _is_int(node):
            on_stack[depth] = node
        paths.append([on_stack[key] for key in sorted(on_stack)])
    return paths


def model(
    spec: dict[str, Any],
    tree_layout: dict[str, Any],
    scope: dict[str, Any],
    step: dict[str, Any],
    path: list[int],
    line_text: str,
    language: str,
) -> dict[str, Any]:
    from .analyzer import _display_value

    values = scope.get(spec["array"])
    if not isinstance(values, list):
        return {"renderer": "segment_tree", "ready": False}
    ids = {entry["id"] for entry in tree_layout["nodes"]}
    in_tree = _function_name(step) in spec["functions"]
    current = scope.get(spec["node"]) if in_tree else None
    view: dict[str, Any] = {
        "renderer": "segment_tree",
        "ready": True,
        "name": spec["array"],
        # Entries past what the tracer read (C++ arrays stop at 50) are unknown, not 0.
        "values": [
            _display_value(values[entry["id"]], language) if entry["id"] < len(values) else None
            for entry in tree_layout["nodes"]
        ],
        "current": current if current in ids else None,
        "path": [node for node in path if node in ids],
        "reading": _read_nodes(spec, line_text, scope, ids) if in_tree else [],
        "uses": [spec["array"]],
    }
    base = scope.get(spec["base"]) if spec["base"] else None
    if isinstance(base, list) and not tree_layout["truncated"]:
        view["base"] = {
            "name": spec["base"],
            "values": [
                _display_value(base[index], language) if 0 <= index < len(base) else None
                for index in range(tree_layout["low"], tree_layout["high"] + 1)
            ],
        }
        view["uses"].append(spec["base"])
    return view


def _read_nodes(spec: dict[str, Any], line_text: str, scope: dict[str, Any], ids: set[int]) -> list[int]:
    """Nodes the line about to run reads: `tree[id*2] >= v` → the left child's id."""
    found: list[int] = []
    for match in re.finditer(rf"(?<![\w.])\b{re.escape(spec['array'])}\s*\[([^\[\]]*)\]", line_text):
        after = line_text[match.end():].lstrip()
        if re.match(r"(?:[-+*/%^|&]|<<|>>)?=(?!=)", after):
            continue  # the entry being written, not read
        index = _integer(_substitute(match.group(1), scope, "cpp"))
        if index in ids and index not in found:
            found.append(index)
    return found


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
