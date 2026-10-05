from pathlib import Path

import pytest

from app.analyzer import _decode_scope
from app.lenses import build_events, enrich_model, extend_catalog, view_model
from app.runner import run_debugger


SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def _trace(filename):
    source = (SAMPLES / filename).read_text(encoding="utf-8")
    result = run_debugger(source)
    cache = {}
    scopes = [_decode_scope(step, cache) for step in result["steps"]]
    return source, result, scopes


@pytest.mark.parametrize("filename,renderer,name,stdout", [
    ("sample8_heap.py", "heap", "heap", "[1, 3, 5, 6, 8]"),
    ("sample9_sliding_window.py", "window", "nums", "2"),
    ("sample10_monotonic_stack.py", "monotonic", "stack", "[-1, -1, 1, 1, 3]"),
    ("sample11_fenwick.py", "fenwick", "bit", "10"),
    ("sample12_kmp.py", "string_match", "text", "[5]"),
    ("sample13_trie.py", "trie", "trie", "True"),
])
def test_real_algorithm_sample_has_supported_lens_and_correct_result(filename, renderer, name, stdout):
    source, result, scopes = _trace(filename)
    assert result["status"] == "completed"
    assert result["steps"][-1]["stdout"].strip() == stdout
    catalog = extend_catalog(source, scopes, result["steps"])
    view = next(view for view in catalog if view["id"] == f"{renderer}:{name}")
    assert view["preferred"]
    models = []
    for index, (step, scope) in enumerate(zip(result["steps"], scopes)):
        step["_source_line"] = source.splitlines()[step["line"] - 1]
        models.append(view_model(view, scope, step, scopes[index - 1] if index else None))
    assert any(model.get("ready") for model in models)


def test_manual_window_and_stack_bindings_use_custom_variable_names():
    scopes = [{"data": [4, 2, 8], "begin": 1, "stop": 2, "running": 10.5, "pending": [1, 2]}]
    bindings = {"mode": "window", "primary": "data", "left": "begin", "right": "stop", "total": "running", "right_exclusive": "true"}
    view = extend_catalog("", scopes, [], bindings=bindings)[0]
    model = view_model(view, scopes[0], {}, bindings=bindings)
    assert model["bounds"] == {"left": 1, "right": 2, "inclusive": False}
    assert model["aggregate"] == {"name": "running", "value": 10.5}
    bindings = {"mode": "monotonic", "primary": "data", "stack": "pending"}
    view = extend_catalog("", scopes, [], bindings=bindings)[0]
    model = view_model(view, scopes[0], {}, bindings=bindings)
    assert view["variable"] == "pending"
    assert model["source_name"] == "data"
    assert model["entries"][0]["data_value"] == 2


def test_fenwick_ranges_are_mathematical_metadata_and_accesses_are_recorded():
    scope = {"bit": [0, 1, 3, 2, 8], "i": 4, "total": 0}
    view = {"renderer": "fenwick", "variable": "bit", "index": "i"}
    model = view_model(view, scope, {"_source_line": "total += bit[i]", "usage": {}})
    assert [(node["index"], node["low"], node["high"]) for node in model["nodes"]] == [(1, 1, 1), (2, 1, 2), (3, 3, 3), (4, 1, 4)]
    assert model["accesses"] == [4]
    assert model["operation"]["kind"] == "query"
    assert "query_path" not in model


def test_dp_dependencies_and_writes_use_actual_values_and_safe_index_arithmetic():
    scope = {"dp": [[1, 2], [3, 0]], "row": 1, "column": 1}
    after = {**scope, "dp": [[1, 2], [3, 5]]}
    model = {"renderer": "grid", "ready": True, "name": "dp", "uses": ["dp"], "values": after["dp"]}
    step = {"_source_line": "dp[row][column] = dp[row-1][column] + dp[row][column-1]", "_after_scope": after,
            "usage": {"cells": {"dp": {"items": [1], "cells": [[1, 1]]}}}}
    enrich_model(model, step, scope)
    assert [(entry["cell"], entry["value"]) for entry in model["dependencies"]] == [([0, 1], 2), ([1, 0], 3)]
    assert model["destinations"] == [{"name": "dp", "cell": [1, 1], "before": 0, "after": 5}]
    assert step["usage"]["reads"]["dp"]["cells"] == [[0, 1], [1, 0]]
    assert model["operation"]["substituted"] == "2 + 3"
    assert model["operation"]["candidate"] == {"value": 5, "expression": "dp[row-1][column] + dp[row][column-1]"}


def test_arbitrary_index_calls_are_never_executed():
    model = {"renderer": "array", "ready": True, "name": "a", "uses": ["a"], "values": [1]}
    step = {"_source_line": "x = a[danger()]", "usage": {}}
    enrich_model(model, step, {"a": [1], "danger": lambda: pytest.fail("user index executed")})
    assert model["operation"]["reads"] == []


def test_dp_candidates_support_only_safe_builtin_arithmetic_and_do_not_call_shadowed_min():
    model = {"renderer": "array", "ready": True, "name": "dp", "uses": ["dp"], "values": [1, 2, 3]}
    scope = {"dp": [1, 2, 3], "i": 2}
    step = {"_source_line": "dp[i] = min(dp[i-1], dp[i-2]) + 5", "usage": {"cells": {"dp": {"items": [2]}}}}
    enrich_model(model, step, scope)
    assert model["operation"]["candidate"]["value"] == 6
    scope["min"] = lambda *args: pytest.fail("shadowed min executed")
    enrich_model(model, step, scope)
    assert "candidate" not in model["operation"]


def test_augmented_dp_candidate_includes_the_previous_destination_value():
    model = {"renderer": "array", "ready": True, "name": "dp", "uses": ["dp"], "values": [1, 2, 3]}
    step = {"_source_line": "dp[i] += dp[i-1]", "usage": {"cells": {"dp": {"items": [2]}}}}
    enrich_model(model, step, {"dp": [1, 2, 3], "i": 2})
    assert model["operation"]["candidate"]["value"] == 5


def test_cpp_dp_keeps_observed_formula_and_values_without_python_evaluation():
    model = {"renderer": "array", "ready": True, "name": "dp", "uses": ["dp"], "values": [-3, -1]}
    step = {"_language": "cpp", "_source_line": "dp[i] = dp[i-1] / 2;", "_after_scope": {"dp": [-3, -1], "i": 1},
            "usage": {"cells": {"dp": {"items": [1]}}}}
    enrich_model(model, step, {"dp": [-3, 0], "i": 1})
    assert "candidate" not in model["operation"]
    assert model["operation"]["substituted"] == "-3 / 2"
    assert model["operation"]["writes"][0]["after"] == -1


def test_sorting_metadata_uses_captured_pivot_bounds_and_merge_buffer():
    scope = {"a": [8, 2, 4], "pivot_index": 1, "lo": 0, "hi": 3, "merged": [2, 4, 8]}
    model = {"renderer": "array", "ready": True, "name": "a", "uses": ["a"], "values": scope["a"]}
    enrich_model(model, {"function": "merge_sort", "_source_line": "a[pivot_index]", "usage": {}}, scope,
                 bindings={"mode": "sorting", "right_exclusive": "true"})
    assert model["sorting"]["pivot"] == {"name": "pivot_index", "index": 1, "value": 2}
    assert model["sorting"]["range"]["inclusive"] is False
    assert model["sorting"]["temporary"]["values"] == [2, 4, 8]
    assert model["operation"]["kind"] == "inspect"


def test_graph_teaching_layer_indegree_and_output_use_recorded_arrays():
    model = {"renderer": "graph", "ready": True, "name": "adj", "nodes": ["0", "1", "2"], "uses": ["adj"], "frontier": None}
    scope = {"adj": [[1], [2], []], "level": [0, 1, 2], "indeg": [0, 0, 1], "order": [0, 1]}
    enrich_model(model, {"_source_line": "indeg[2] -= 1", "usage": {}}, scope)
    assert model["teaching"]["layers"]["values"] == {"0": 0, "1": 1, "2": 2}
    assert model["teaching"]["indegree"]["values"]["2"] == 1
    assert model["teaching"]["output"]["values"] == [0, 1]


def test_explicit_graph_indegree_output_and_closed_sort_range_bindings():
    model = {"renderer": "graph", "ready": True, "name": "adj", "nodes": ["0", "1"], "uses": ["adj"], "frontier": None}
    scope = {"adj": [[1], []], "remaining": [0, 1], "completed": [0]}
    after = {**scope, "remaining": [0, 0]}
    step = {"_source_line": "remaining[1] -= 1", "_after_scope": after,
            "usage": {"cells": {"remaining": {"items": [1]}}}}
    enrich_model(model, step, scope, bindings={"indegree": "remaining", "output": "completed"})
    assert model["operation"]["writes"] == [{"name": "remaining", "index": 1, "before": 1, "after": 0}]
    assert model["teaching"]["indegree"]["values"]["1"] == 0
    assert model["teaching"]["output"]["values"] == [0]
    sorting = {"renderer": "array", "ready": True, "name": "a", "uses": ["a"], "values": [1, 2]}
    enrich_model(sorting, {"usage": {}}, {"a": [1, 2], "l": 0, "r": 1},
                 bindings={"mode": "sorting", "right_exclusive": "false"})
    assert sorting["sorting"]["range"]["inclusive"] is True


def test_integrated_manual_segment_tree_selects_the_bound_source_array():
    source = """a = [2, 4, 1, 5]
seg = [0] * 16
tags = [0] * 16
def build(node, lo, hi):
    if lo == hi:
        seg[node] = a[lo]
        return
    mid = (lo + hi) // 2
    build(node * 2, lo, mid)
    build(node * 2 + 1, mid + 1, hi)
    seg[node] = seg[node * 2] + seg[node * 2 + 1]
build(1, 0, 3)
tags[1] = 7
"""
    result = run_debugger(source, bindings={"mode": "segment_tree", "primary": "seg", "lazy": "tags"})
    assert result["algorithm"]["auto_renderer"] == "segment_tree"
    view = next(view for view in result["algorithm"]["views"] if view["id"] == "segment_tree:seg")
    assert view["variable"] == "seg"
    assert result["steps"][-1]["visualization"]["name"] == "seg"
    assert result["steps"][-1]["visualization"]["lazy"]["values"]["1"] == 7
    assert result["algorithm"]["evidence"] == ["chosen by you"]


def test_comments_and_literal_examples_do_not_offer_algorithm_lenses_or_reads():
    scopes = [{"a": [2, 4], "heap": [2, 4], "root": {"a": {}}, "left": 0, "right": 1, "i": 0}]
    source = 'example = "heappush(heap, 1); a[left]; a[right]; Trie"\n# heappop(heap)\n'
    assert extend_catalog(source, scopes, []) == []
    model = {"renderer": "array", "ready": True, "name": "a", "uses": ["a"], "values": [2, 4]}
    step = {"_source_line": 'print("a[i]") # a[i]', "usage": {}}
    enrich_model(model, step, scopes[0])
    assert model["operation"]["reads"] == []


def test_cpp_comment_and_literal_reads_are_ignored_while_python_floor_division_is_preserved():
    model = {"renderer": "array", "ready": True, "name": "a", "uses": ["a", "b"], "values": [8]}
    scope = {"a": [8], "b": [2], "i": 0}
    for source in ('cout << "a[i]"; // a[i]', '/* a[i] */ x = 3;'):
        enrich_model(model, {"_language": "cpp", "_source_line": source, "usage": {}}, scope)
        assert model["operation"]["reads"] == []
    enrich_model(model, {"_language": "python", "_source_line": "x = a[i] // b[i]", "usage": {}}, scope)
    assert [entry["name"] for entry in model["operation"]["reads"]] == ["a", "b"]


def test_heap_does_not_invent_internal_sift_events():
    before = {"heap": [2, 4, 8]}
    after = {"heap": [1, 2, 8, 4]}
    step = {"_source_line": "heappush(heap, 1)", "_after_scope": after, "usage": {"cells": {"heap": {"items": [0, 1, 3], "cells": []}}}}
    model = view_model({"renderer": "heap", "variable": "heap", "order": "min"}, before, step)
    assert model["operation"]["kind"] == "push"
    assert "sift" not in model["operation"]["label"].lower()
    assert model["nodes"][2]["parent"] == 0


def test_heap_import_aliases_and_max_heap_names_preserve_known_order():
    scopes = [{"pending": [4, 2], "small": [1, 3]}]
    source = "import heapq as h\nfrom heapq import heappush as push\nh.heapify_max(pending)\npush(small, 1)\n"
    views = extend_catalog(source, scopes, [])
    assert {view["id"]: view["order"] for view in views} == {"heap:pending": "max", "heap:small": "min"}
    cpp = "priority_queue<int, vector<int>, MyCompare> pending;"
    views = extend_catalog(cpp, scopes, [], language="cpp")
    assert views[0]["order"] == "unknown"


def test_partial_capture_reports_actual_length_and_keeps_captured_values():
    class Partial(list):
        total = 1000
    step = {"locals": {"heap": {"type": "list", "length": 1000, "truncated": True}}, "_source_line": "heap[0]"}
    model = view_model({"renderer": "heap", "variable": "heap"}, {"heap": Partial([3, 5, 7])}, step)
    assert model["values"] == [3, 5, 7]
    assert model["length"] == 1000
    assert model["truncated"]


def test_specialized_values_preserve_integers_beyond_javascript_precision():
    value = 2**63 - 1
    model = view_model({"renderer": "heap", "variable": "heap"}, {"heap": [value]}, {})
    assert model["values"] == [str(value)]
    assert model["top"] == str(value)
    assert model["nodes"][0]["value"] == str(value)


def test_integrated_heap_operations_stay_on_the_highlighted_source_line():
    source, result, _ = _trace("sample8_heap.py")
    assert "heap:heap" in {view["id"] for view in result["algorithm"]["views"]}
    pushes = [step for step in result["steps"] if step.get("views", {}).get("heap:heap", {}).get("operation", {}).get("kind") == "push"]
    assert pushes
    assert all("heap.append(value)" in source.splitlines()[step["line"] - 1] or "heappush(heap, value)" in source.splitlines()[step["line"] - 1] for step in pushes)
    assert all("_source_line" not in step and "_after_scope" not in step for step in result["steps"])


def test_string_alignment_is_unavailable_until_indices_are_recorded_and_prefix_is_partial():
    class Partial(list):
        total = 10
    model = view_model({"renderer": "string_match", "variable": "text", "pattern": "pattern"},
                       {"text": "abc", "pattern": "bc", "prefix": Partial([0, 0])}, {})
    assert model["alignment"] is None
    assert model["prefix_name"] == "prefix"
    assert model["truncated"]
    assert "comparison" not in model


def test_integrated_string_comparison_occurs_only_on_the_comparison_line():
    source = 'text="ab"\npattern="b"\ni=0\nj=0\nif text[i] != pattern[j]:\n    i += 1\nprint(i)\n'
    result = run_debugger(source)
    models = [(step, step.get("views", {}).get("string_match:text", {})) for step in result["steps"]]
    compared = [(step, model) for step, model in models if model.get("comparison")]
    assert compared
    assert all(step["line"] == 5 for step, _ in compared)
    assert compared[0][1]["comparison"] == {"left": "a", "right": "b", "equal": False}


def test_trie_terminals_and_prefix_path_come_from_state_not_word_prediction():
    scope = {"trie": {"a": {"end": True, "t": {"end": True}}, "b": {}}, "prefix": "at", "ch": "t"}
    model = view_model({"renderer": "trie", "variable": "trie"}, scope, {})
    assert model["current"] == "root/a/t"
    assert model["path"] == ["root", "root/a", "root/a/t"]
    assert {node["id"] for node in model["nodes"] if node["terminal"]} == {"root/a", "root/a/t"}
    assert model["character"] == "t"


def test_manual_segment_lazy_binding_indexes_values_by_node_id():
    model = {"renderer": "segment_tree", "ready": True, "name": "seg", "uses": ["seg"]}
    scope = {"tags": [0, 5, 0, 2], "begin": 2, "end": 4}
    enrich_model(model, {"_source_line": "tags[1] = 5", "usage": {}}, scope,
                 bindings={"lazy": "tags", "query_left": "begin", "query_right": "end"})
    assert model["lazy"]["values"] == {"0": 0, "1": 5, "2": 0, "3": 2}
    assert model["query"] == {"low": 2, "high": 4, "inclusive": True}


def test_manual_graph_frontier_maps_distance_vertex_pairs_to_vertices():
    model = {"renderer": "graph", "ready": True, "name": "adj", "nodes": ["1", "2", "3"], "uses": ["adj"], "frontier": None}
    scope = {"adj": [[], [2, 3], [], []], "pending": [[7, 2], [3, 3]], "shortest": [0, 0, 7, 3], "active": 1}
    enrich_model(model, {"_source_line": "pending[0]", "usage": {}}, scope,
                 bindings={"frontier": "pending", "distance": "shortest", "index": "active"})
    assert model["frontier"]["items"] == ["2", "3"]
    assert model["frontier"]["entries"] == ["(7, 2)", "(3, 3)"]
    assert model["labels"]["name"] == "shortest"
    assert model["current"] == "1"


def test_event_index_contains_actual_calls_returns_and_state_only():
    steps = [{"event": "call", "function": "dfs", "line": 1},
             {"event": "line", "line": 2, "usage": {}},
             {"event": "line", "line": 3, "usage": {"cells": {"path": {"items": [0]}}}},
             {"event": "return", "function": "dfs", "line": 4}]
    events = build_events(steps)
    assert [(event["index"], event["kind"]) for event in events] == [(0, "call"), (2, "state"), (3, "return")]
    assert all("prune" not in event["label"].lower() for event in events)
