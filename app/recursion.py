"""Build a recursion tree (one node per function call) from a trace's call stacks."""

from __future__ import annotations

import re
from typing import Any


# Calls are lightweight metadata; rendering budgets are applied by the focused view.
# The trace itself has a bounded step count, so keeping call identities avoids losing
# the current path once an exhaustive search passes its 400th call.
MAX_TREE_NODES = 20_000
MAX_LABEL_LENGTH = 48
_CPP_CHAR_VALUE = re.compile(r"-?\d+ ('(?:\\.|[^'\\])*')")


def build_recursion_tree(
    steps: list[dict[str, Any]],
    language: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return the tree plus, for every step, the node that is executing and its parameter names.

    Nodes are created in call order and never removed: `start_step` is the step where the call
    begins and `end_step` the last step its frame was on the stack (None while still running).
    """
    nodes: list[dict[str, Any]] = []
    path: list[int | None] = []
    previous_frames: list[dict[str, Any]] = []
    entry_lines: dict[str, int] = {}
    per_step: list[dict[str, Any]] = []
    truncated = False
    call_count = 0

    for index, step in enumerate(steps):
        frames = step.get("stack") or []
        depth = int(step.get("depth", len(frames)))
        if language == "cpp":
            keep = _shared_depth(previous_frames, frames)
            if frames and _starts_new_call(step, previous_frames, frames, language, entry_lines):
                keep = min(keep, len(frames) - 1)
        else:
            # Python steps carry the full depth and a `call` event for every call, which is
            # enough even when `stack` keeps only the innermost frames of a deep recursion.
            keep = depth - 1 if step.get("event") == "call" else depth
        keep = max(0, min(keep, len(path)))

        for node_id in path[keep:]:
            if node_id is not None:
                nodes[node_id]["end_step"] = index - 1
        path = path[:keep]

        for level in range(keep, depth):
            if len(nodes) >= MAX_TREE_NODES:
                truncated = True
                path.append(None)
                continue
            frame = _frame_at(frames, depth, level)
            label, title, params = _call_label(step, frame, is_top=level == depth - 1, language=language)
            parent = path[-1] if path else None
            # Calls are numbered in the order they start; the root (main / <module>) has none.
            if parent is not None:
                call_count += 1
            nodes.append({
                "id": len(nodes),
                "order": call_count if parent is not None else None,
                "parent": parent,
                "function": frame.get("function"),
                "label": label,
                "title": title,
                "params": params,
                "start_step": index,
                "end_step": None,
                "return_value": None,
            })
            entry_lines.setdefault(str(frame.get("function")), frame.get("line"))
            path.append(len(nodes) - 1)

        current = path[-1] if path else None
        if language != "cpp" and step.get("event") == "return" and current is not None and "return_value" in step:
            nodes[current]["return_value"] = _format_value(step["return_value"])
            nodes[current]["end_step"] = index
        per_step.append({
            "current": current,
            "uses": list(nodes[current]["params"]) if current is not None else [],
        })
        previous_frames = frames

    return {"nodes": nodes, "truncated": truncated}, per_step


def _frame_at(frames: list[dict[str, Any]], depth: int, level: int) -> dict[str, Any]:
    """Frame at stack `level` when `frames` holds the outermost frame plus the innermost ones."""
    if depth <= len(frames):
        return frames[level]
    inner_start = depth - (len(frames) - 1)
    if level == 0:
        return frames[0]
    if level >= inner_start:
        return frames[1 + level - inner_start]
    return {"function": "…", "line": None}


def _shared_depth(previous: list[dict[str, Any]], frames: list[dict[str, Any]]) -> int:
    depth = 0
    for before, now in zip(previous, frames):
        if before.get("function") != now.get("function"):
            break
        depth += 1
    return depth


def _starts_new_call(
    step: dict[str, Any],
    previous: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    language: str,
    entry_lines: dict[str, int],
) -> bool:
    """Detect a call that replaces a sibling at the same depth, e.g. `f(n - 1) + f(n - 2)`."""
    if language != "cpp":
        return step.get("event") == "call"
    # GDB traces only report lines, so a sibling call shows up as the same function at the same
    # depth jumping back to its first line with different arguments. A loop at the top of the
    # function also returns to that line, but keeps the same arguments.
    if not previous or len(previous) != len(frames):
        return False
    before, now = previous[-1], frames[-1]
    return (
        before.get("function") == now.get("function")
        and before.get("args") != now.get("args")
        and before.get("line") != now.get("line")
        and now.get("line") == entry_lines.get(str(now.get("function")))
    )


def _call_label(
    step: dict[str, Any],
    frame: dict[str, Any],
    *,
    is_top: bool,
    language: str,
) -> tuple[str, str, list[str]]:
    """Return the node label (argument values only, to keep the tree narrow), the full
    `name=value` text for the tooltip, and the parameter names."""
    function = str(frame.get("function") or "?")
    if function == "<module>":
        return function, function, []
    if language == "cpp":
        arguments = _CPP_CHAR_VALUE.sub(r"\1", str(frame.get("args") or ""))
        pairs = [
            (name, value)
            for name, value in re.findall(r"([A-Za-z_]\w*)=((?:'(?:\\.|[^'\\])*'|[^,])*)", arguments)
        ]
    elif is_top and step.get("event") == "call":
        # At a Python call event the frame's locals are exactly its parameters, in order.
        pairs = [(name, _format_value(value)) for name, value in (step.get("locals") or {}).items()]
    else:
        return f"{function}(…)", f"{function}(…)", []
    values = ",".join(value.strip() for _, value in pairs)
    full = ", ".join(f"{name}={value.strip()}" for name, value in pairs)
    return _clip(f"{function}({values})"), f"{function}({full})", [name for name, _ in pairs]


def _format_value(value: Any) -> str:
    if not isinstance(value, dict):
        return "?"
    kind = value.get("type")
    if kind == "str":
        return repr(value.get("value", ""))
    if kind == "bool":
        return "True" if value.get("value") else "False"
    if kind == "none":
        return "None"
    if kind in {"int", "float"}:
        return str(value.get("value"))
    if kind in {"list", "tuple", "set", "frozenset"}:
        return f"{kind}[{len(value.get('items') or [])}]"
    if kind == "dict":
        return f"dict[{len(value.get('entries') or [])}]"
    if kind == "reference":
        return "…"
    return str(value.get("value", kind))


def _clip(text: str) -> str:
    return text if len(text) <= MAX_LABEL_LENGTH else f"{text[: MAX_LABEL_LENGTH - 1]}…"
