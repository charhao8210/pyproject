from collections import Counter, defaultdict, deque
import io

import pytest

from app.runner import run_debugger
from app.serializer import SerializationContext, serialize_locals, serialize_value
from app.tracer import CappedOutput, _safe_builtins, trace_code
from app.validator import SourceValidationError, validate_source
from types import SimpleNamespace


@pytest.mark.parametrize("source", [
    "import heapq as h\n",
    "from heapq import heappush, heappop, heapify\n",
    "import bisect\nfrom bisect import bisect_left as lower_bound\n",
    "from collections import deque, defaultdict, Counter\n",
    "import math\nfrom math import gcd, isqrt, inf\n",
    "import sys\nfrom sys import stdin as input_stream\n",
])
def test_algorithm_import_allowlist_accepts_public_members(source: str) -> None:
    validate_source(source)


@pytest.mark.parametrize("source", [
    "import os\n",
    "from os import path\n",
    "import heapq.os\n",
    "from heapq import _siftdown\n",
    "from collections import namedtuple\n",
    "from collections import *\n",
    "from math import __loader__\n",
    "from sys import modules\n",
    "from .math import sqrt\n",
    "eval('1 + 1')\n",
    "heapq.heapify.__globals__\n",
])
def test_algorithm_imports_keep_validation_restrictions(source: str) -> None:
    with pytest.raises(SourceValidationError):
        validate_source(source)


def test_runtime_imports_return_only_allowlisted_namespaces() -> None:
    safe_sys = SimpleNamespace(stdin=io.StringIO("3\n"))
    safe = _safe_builtins(safe_sys.stdin, CappedOutput(), safe_sys)
    importer = safe["__import__"]
    assert importer("sys") is safe_sys
    assert importer("math").gcd(24, 18) == 6
    assert set(vars(importer("collections"))) == {"deque", "defaultdict", "Counter"}
    assert not hasattr(importer("heapq"), "os")
    assert not hasattr(importer("heapq"), "_siftdown")
    assert not hasattr(importer("collections"), "sys")
    assert not hasattr(importer("sys"), "modules")
    assert "eval" not in safe and "open" not in safe
    for name, members, level in [("os", (), 0), ("math", ("*",), 0), ("sys", ("modules",), 0), ("math", (), 1)]:
        with pytest.raises(ImportError):
            importer(name, fromlist=members, level=level)


@pytest.mark.parametrize("source", ["import os", "from collections import namedtuple", "from sys import stdout"])
def test_runtime_enforces_allowlist_even_without_ast_validation(source: str) -> None:
    result = trace_code(source)
    assert result["status"] == "exception"
    assert result["error"]["type"] == "ImportError"


def test_real_heapq_calls_execute_and_feed_heap_lens() -> None:
    source = """import heapq
pq = [7, 2, 9]
heapq.heapify(pq)
heapq.heappush(pq, 1)
first = heapq.heappop(pq)
print(first, pq[0])
"""
    result = run_debugger(source, bindings={"mode": "heap", "primary": "pq"})
    assert result["status"] == "completed"
    assert result["steps"][-1]["stdout"] == "1 2\n"
    heap_views = [view for view in result["algorithm"]["views"] if view["renderer"] == "heap"]
    assert heap_views
    states = [step["views"].get(heap_views[0]["id"]) for step in result["steps"]]
    assert any(state and state.get("ready") and state["top"] == 1 for state in states)


def test_real_deque_operations_remain_indexed_trace_sequences() -> None:
    source = """from collections import deque
q = deque([1, 2, 3])
q.append(4)
front = q.popleft()
q.appendleft(9)
print(front, list(q))
"""
    result = run_debugger(source)
    assert result["status"] == "completed"
    assert result["steps"][-1]["stdout"] == "1 [9, 2, 3, 4]\n"
    state = result["steps"][-1]["locals"]["q"]
    assert state["type"] == "list" and state["class_name"] == "deque"
    assert state["length"] == 4
    assert [item["value"] for item in state["items"]] == [9, 2, 3, 4]


def test_bisect_math_and_collection_helpers_execute_with_aliases() -> None:
    result = run_debugger("""from bisect import insort as insert, bisect_left
from collections import Counter, defaultdict
from math import gcd, isqrt
a = [1, 5]
insert(a, 3)
counts = Counter('aba')
groups = defaultdict(list)
groups['x'].append(4)
print(a, bisect_left(a, 3), counts['a'], groups['x'], gcd(24, 18), isqrt(17))
""")
    assert result["status"] == "completed"
    assert result["steps"][-1]["stdout"] == "[1, 3, 5] 1 2 [4] 6 4\n"
    assert result["steps"][-1]["locals"]["counts"]["type"] == "dict"
    assert result["steps"][-1]["locals"]["groups"]["type"] == "dict"


def test_deque_capture_preserves_length_limit_and_maxlen() -> None:
    value = deque(range(80), maxlen=100)
    state = serialize_value(value, context=SerializationContext(max_items=12))
    assert state["type"] == "list" and state["class_name"] == "deque"
    assert state["length"] == 80 and state["maxlen"] == 100 and state["truncated"]
    assert [item["value"] for item in state["items"]] == list(range(12))
    assert len(value) == 80, "capturing must not consume or modify a deque"


def test_deque_identity_cycles_and_depth_limits() -> None:
    value: deque = deque()
    value.append(value)
    state = serialize_locals({"q": value, "alias": value})
    assert state["q"]["items"][0]["type"] == "reference"
    assert state["alias"]["object_id"] == state["q"]["object_id"]
    shallow = serialize_value(value, context=SerializationContext(max_depth=0))
    assert shallow["length"] == 1 and shallow["truncated"] and "items" not in shallow


@pytest.mark.parametrize("value", [Counter("aba"), defaultdict(list, {"a": [1, 2]})])
def test_collection_mappings_use_existing_dictionary_wire_shape(value: dict) -> None:
    state = serialize_value(value)
    assert state["type"] == "dict"
    assert state["python_type"] in {"Counter", "defaultdict"}
    assert state["entries"] and "items" not in state
    assert "class_name" not in state, "a mapping must not decode as a user object's fields"
