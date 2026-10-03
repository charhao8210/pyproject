from __future__ import annotations

import math
import types
from dataclasses import dataclass, field
from typing import Any


MAX_DEPTH = 4
MAX_ITEMS = 50
MAX_STRING_LENGTH = 1_000
# Runs of trailing zeros at least this long are folded into one note in the UI.
MIN_TRAILING_FILL = 10
# Longer sequences are not checked for an all-zero unread tail.
MAX_TAIL_SCAN_ITEMS = 1_000_000


@dataclass
class SerializationContext:
    seen: set[int] = field(default_factory=set)
    max_depth: int = MAX_DEPTH
    max_items: int = MAX_ITEMS


def serialize_locals(
    values: dict[str, Any],
    *,
    context: SerializationContext | None = None,
) -> dict[str, dict[str, Any]]:
    context = context or SerializationContext()
    return {
        name: serialize_value(value, context=context)
        for name, value in values.items()
        if not name.startswith("__")
    }


def serialize_value(
    value: Any,
    *,
    context: SerializationContext | None = None,
    depth: int = 0,
) -> dict[str, Any]:
    context = context or SerializationContext()

    if value is None:
        return {"type": "none", "value": None}
    if isinstance(value, bool):
        return {"type": "bool", "value": value}
    if isinstance(value, int):
        return {"type": "int", "value": value}
    if isinstance(value, float):
        rendered = value if math.isfinite(value) else str(value)
        return {"type": "float", "value": rendered}
    if isinstance(value, str):
        if len(value) <= MAX_STRING_LENGTH:
            return {"type": "str", "value": value}
        return {
            "type": "str",
            "value": value[:MAX_STRING_LENGTH],
            "truncated": True,
        }
    if isinstance(value, bytes):
        return {
            "type": "bytes",
            "value": value[:100].hex(),
            "truncated": len(value) > 100,
        }

    if isinstance(value, (list, tuple, dict, set, frozenset)):
        return _serialize_container(value, context, depth)

    if isinstance(value, types.FunctionType):
        return {"type": "function", "value": value.__name__}
    if isinstance(value, range):
        return {
            "type": "range",
            "value": {
                "start": value.start,
                "stop": value.stop,
                "step": value.step,
            },
        }

    type_name = type(value).__name__
    return {
        "type": "object",
        "class_name": type_name,
        "object_id": id(value),
        "value": f"<{type_name}>",
    }


def _serialize_container(
    value: list[Any] | tuple[Any, ...] | dict[Any, Any] | set[Any] | frozenset[Any],
    context: SerializationContext,
    depth: int,
) -> dict[str, Any]:
    object_id = id(value)
    if object_id in context.seen:
        return {"type": "reference", "object_id": object_id}

    context.seen.add(object_id)
    type_name = type(value).__name__
    result: dict[str, Any] = {"type": type_name, "object_id": object_id}

    if depth >= context.max_depth:
        result["truncated"] = True
        return result

    if isinstance(value, dict):
        pairs = list(value.items())
        result["entries"] = [
            {
                "key": serialize_value(key, context=context, depth=depth + 1),
                "value": serialize_value(item, context=context, depth=depth + 1),
            }
            for key, item in pairs[: context.max_items]
        ]
        if len(pairs) > context.max_items:
            result["truncated"] = True
        return result

    items = list(value)
    result["items"] = [
        serialize_value(item, context=context, depth=depth + 1)
        for item in items[: context.max_items]
    ]
    if len(items) > context.max_items:
        result["truncated"] = True
        # The real size, so a view can say "0–49 of 80" instead of looking complete.
        result["length"] = len(items)
    if isinstance(value, (list, tuple)):
        unread_zero = None
        if context.max_items < len(items) <= MAX_TAIL_SCAN_ITEMS:
            last = items[-1]
            unread = len(items) - context.max_items
            zeros = items.count(last) - items[: context.max_items].count(last)
            if type(last) in (int, float, bool) and last == 0 and zeros == unread:
                unread_zero = serialize_value(last, context=context, depth=depth + 1)
        fill = trailing_fill(result["items"], len(items), unread_zero)
        if fill:
            result["fill"] = fill
            result["length"] = len(items)
    return result


def is_zero(value: dict[str, Any]) -> bool:
    return value.get("type") in {"int", "float", "bool"} and value.get("value") in (0, False)


def trailing_fill(
    items: list[dict[str, Any]],
    length: int,
    unread_zero: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Describe a long run of trailing zeros as `{"from": index, "value": zero}`.

    `items` holds the first entries of a sequence of `length`; entries past them
    count only when `unread_zero` says they were checked and are all that zero.
    """
    if length > len(items) and unread_zero is None:
        return None
    zero = unread_zero
    start = len(items)
    while start > 0 and is_zero(items[start - 1]) and (zero is None or items[start - 1] == zero):
        zero = items[start - 1]
        start -= 1
    if zero is None or length - start < MIN_TRAILING_FILL:
        return None
    return {"from": start, "value": zero}
