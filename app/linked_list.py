"""Linked List view: nodes as `[value | •]` boxes joined by `next` arrows.

Approved layout (2026-11-11): every variable pointing at a node is labelled above it (and kept
out of Variables), `∅` ends a list, a cycle draws a line back, a long list shows its first 6
and last 2 nodes with `… N …` between them, and nodes a variable points at are always drawn.
A node is an object of the program's own class with a `next` field; the box shows its value
field (val/value/data/key). Built from the step's serialized values, which keep each node's
`object_id`, so shared and circular nodes stay one node.
"""

from __future__ import annotations

import re
from typing import Any

from .containers import QUEUE_HEAD, QUEUE_TAIL, entry_text

LINK_FIELD = "next"
VALUE_FIELDS = ("val", "value", "data", "key")


def _index(value: Any, registry: dict[Any, dict[str, Any]]) -> None:
    if not isinstance(value, dict):
        return
    if value.get("object_id") is not None and value.get("type") != "reference":
        registry.setdefault(value["object_id"], value)
    for item in value.get("items", []):
        _index(item, registry)
    for entry in value.get("entries", []):
        _index(entry.get("key"), registry)
        _index(entry.get("value"), registry)


def _fields(node: dict[str, Any]) -> dict[str, Any]:
    return {entry["key"].get("value"): entry["value"] for entry in node.get("entries", []) if isinstance(entry.get("key"), dict)}


def _is_node(value: Any) -> bool:
    # A node past the serializer's limit has no fields: the chain before it ends in `more`.
    return (
        isinstance(value, dict)
        and value.get("type") == "dict"
        and value.get("class_name") not in (None, "dict")
        and LINK_FIELD in _fields(value)
    )


def _node_text(node: dict[str, Any], language: str) -> str:
    fields = _fields(node)
    if not fields:
        return "…"
    name = next((field for field in VALUE_FIELDS if field in fields), None)
    if name is None:
        name = next((field for field in fields if field not in (LINK_FIELD, "prev")), None)
    value = fields.get(name) if name is not None else None
    if isinstance(value, dict) and value.get("type") in {"none", "bool", "int", "float", "str"}:
        return entry_text(value.get("value"), language)
    return "{…}" if value is not None else ""


def pointer_targets(step: dict[str, Any]) -> tuple[dict[str, Any], dict[Any, dict[str, Any]]]:
    """Variable name → the node it points at, in scope order, and every node by object id."""
    serialized = {**(step.get("globals") or {}), **(step.get("locals") or {})}
    registry: dict[Any, dict[str, Any]] = {}
    for value in serialized.values():
        _index(value, registry)
    nodes = {object_id: value for object_id, value in registry.items() if _is_node(value)}
    targets = {}
    for name, value in serialized.items():
        if isinstance(value, dict) and value.get("object_id") in nodes:
            targets[name] = value["object_id"]
    return targets, nodes


def linked_list_model(step: dict[str, Any], line_text: str, language: str) -> dict[str, Any]:
    targets, nodes = pointer_targets(step)
    if not targets:
        return {"renderer": "linked_list", "ready": False}
    following: dict[Any, Any] = {}
    for object_id, node in nodes.items():
        link = _fields(node).get(LINK_FIELD)
        if not isinstance(link, dict) or link.get("type") == "none":
            following[object_id] = None
        elif link.get("object_id") in nodes:
            following[object_id] = link["object_id"]
        else:
            following[object_id] = "more"
    pointed: dict[Any, list[str]] = {}
    for name, object_id in targets.items():
        pointed.setdefault(object_id, []).append(name)

    # Every node a variable reaches, then chains from the ones nothing points at (a reversal
    # half done has two), then whatever is left (a pure cycle).
    reached: list[Any] = []
    for start in pointed:
        current = start
        while current in nodes and current not in reached:
            reached.append(current)
            current = following.get(current)
    pointed_at = {following[object_id] for object_id in reached}
    starts = [object_id for object_id in pointed if object_id not in pointed_at] + list(pointed)
    placed: dict[Any, tuple[int, int]] = {}
    chains: list[tuple[list[Any], dict[str, Any], Any]] = []
    for start in starts:
        if start in placed:
            continue
        chain: list[Any] = []
        current = start
        while current in nodes and current not in placed:
            placed[current] = (len(chains), len(chain))
            chain.append(current)
            current = following.get(current)
        if current is None:
            end: dict[str, Any] = {"kind": "none"}
        elif current == "more":
            end = {"kind": "more"}
        elif placed[current][0] == len(chains):
            end = {"kind": "cycle", "to": str(current)}
        else:
            end = {"kind": "joins", "to": str(current), "text": _node_text(nodes[current], language)}
        chains.append((chain, end, current))

    values = {str(object_id): _node_text(nodes[object_id], language) for object_id in placed}
    rows = []
    for chain, end, target in chains:
        keep = {position for position in range(len(chain)) if position < QUEUE_HEAD or position >= len(chain) - QUEUE_TAIL}
        keep |= {position for position, object_id in enumerate(chain) if object_id in pointed}
        if end["kind"] == "cycle":
            keep.add(chain.index(target))
        items: list[dict[str, Any]] = []
        last = -1
        for position in sorted(keep):
            if position - last > 1:
                items.append({"gap": position - last - 1})
            object_id = chain[position]
            items.append({"id": str(object_id), "text": values[str(object_id)], "pointers": pointed.get(object_id, [])})
            last = position
        rows.append({"items": items, "end": end})

    reading = [
        str(object_id)
        for name, object_id in targets.items()
        if re.search(rf"(?<![\w.]){re.escape(name)}\s*(?:\.|->)", line_text)
    ]
    return {
        "renderer": "linked_list",
        "ready": True,
        "name": next(iter(targets)),
        "size": len(placed),
        # Some chain goes on past what was read, so `size` is a lower bound.
        "partial": any(end["kind"] == "more" for _, end, _ in chains),
        "rows": rows,
        # Every drawn node's text by id, for `_mark_writes`.
        "values": values,
        "reading": list(dict.fromkeys(reading)),
        "uses": list(targets),
    }
