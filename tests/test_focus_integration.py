from fastapi.testclient import TestClient

from app import toolchain
from app.main import app
from app.runner import run_debugger
from app.usage import variable_usage


def test_manual_dp_uses_custom_table_with_absolute_coordinates_past_old_limits():
    code = "table = [[0]*75 for _ in range(70)]\nr = 65\nc = 70\ntable[r-1][c] = 2\ntable[r][c-1] = 3\ntable[r][c] = table[r-1][c] + table[r][c-1]\nprint(table[r][c])"
    result = run_debugger(code, capture_items=100, bindings={"mode": "dp", "primary": "table", "row": "r", "column": "c"})
    assert result["status"] == "completed"
    assert result["algorithm"]["kind"] == "dynamic_programming"
    step = next(step for step in result["steps"] if step["event"] == "line" and step["line"] == 6)
    view = step["visualization"]
    assert view["captured_rows"][65][70] == 5
    assert view["current_cell"] == [65, 70]
    assert {tuple(entry["cell"]) for entry in view["dependencies"]} == {(64, 70), (65, 69)}
    assert view["destinations"][0]["before"] == 0
    assert view["destinations"][0]["after"] == 5


def test_larger_capture_preserves_long_array_location_and_exact_values():
    result = run_debugger("a = list(range(120))\ni = 87\na[i] = 9007199254740993\nprint(a[i])", capture_items=200)
    step = next(step for step in result["steps"] if step["event"] == "line" and step["line"] == 3)
    view = step["views"]["array:a"]
    assert view["captured_values"][87] == 9007199254740993
    assert any(marker["index"] == 87 for marker in view["beyond"])
    assert view["operation"]["writes"][0]["index"] == 87


def test_recursion_keeps_current_calls_and_returns_after_400_calls():
    result = run_debugger("def dfs(n):\n    if n == 0:\n        return 1\n    return dfs(n-1) + dfs(n-1)\nprint(dfs(8))", timeout_seconds=10)
    tree = result["algorithm"]["recursion_tree"]
    assert len(tree["nodes"]) > 400
    assert not tree["truncated"]
    assert all(node["end_step"] is not None for node in tree["nodes"])
    assert any(step["views"]["recursion_tree"]["current"] > 400 for step in result["steps"])
    assert result["steps"][-1]["stdout"] == "256\n"


def test_manual_pairing_of_seventh_array_is_computed_without_another_run():
    code = "\n".join(f"a{i} = [{i}, {i+1}]" for i in range(8)) + "\na7[1] = 99"
    result = run_debugger(code, bindings={"mode": "dp", "primary": "a7"})
    assert not result["algorithm"]["binding_warnings"]
    assert result["steps"][-1]["visualization"]["name"] == "a7"
    assert result["steps"][-1]["visualization"]["values"] == [7, 99]


def test_caller_line_displays_same_frame_effect_and_recursion_location():
    code = "a=[1,2]\ndef change():\n    a[0]=9\nchange()\nprint(a)"
    result = run_debugger(code)
    caller = next(step for step in result["steps"] if step["event"] == "line" and step["line"] == 4)
    assert caller["views"]["array:a"]["values"] == [9, 2]
    assert caller["views"]["array:a"]["operation"]["writes"][0]["after"] == 9
    assert caller["views"]["call_tree"]["frames"][-1]["function"] == "<module>"


def test_manual_monotonic_pairs_data_and_separate_stack():
    result = run_debugger("data=[4,2,8]\npending=[1,2]", bindings={"mode": "monotonic", "primary": "data", "stack": "pending"})
    assert not result["algorithm"]["binding_warnings"]
    view = result["steps"][-1]["visualization"]
    assert view["renderer"] == "monotonic"
    assert view["name"] == "pending"
    assert view["entries"][0]["data_value"] == 2


def test_unsuitable_manual_binding_warns_and_retains_a_usable_view():
    result = run_debugger("x=1\nprint(x)", bindings={"mode": "dp", "primary": "missing"})
    assert result["algorithm"]["binding_warnings"]
    assert result["steps"][-1]["visualization"]["renderer"] == "execution"


def test_dense_graph_explains_its_drawing_budget():
    result = run_debugger("n=12\ngraph=[list(range(n)) for _ in range(n)]\nu=11")
    view = result["steps"][-1]["views"]["graph:graph"]
    assert view["edges_total"] == 144
    assert view["edges_truncated"]
    assert len(view["edges"]) == 100


def test_cpp_sibling_frames_do_not_attribute_new_arguments_to_previous_call():
    steps = [{"function": "f", "depth": 2, "line": line, "event": "line", "_frame_id": frame_id,
              "locals": {"n": {"type": "int", "value": n}}}
             for line, frame_id, n in [(1, 1, 1), (2, 1, 1), (1, 2, 9), (2, 2, 9)]]
    usage = variable_usage("int f(int n) {\n return n;\n}", "cpp", steps, [{"n": n} for n in [1, 1, 9, 9]])
    assert usage[1]["next"] == {}
    assert usage[2]["changed"] == []


def test_api_validates_capture_and_reports_missing_cpp_toolchain(monkeypatch, tmp_path):
    with TestClient(app) as client:
        assert client.post("/api/debug", json={"code": "x=1", "capture_items": 501}).status_code == 422
        assert client.post("/api/debug", json={"code": "x=1", "capture_depth": 9}).status_code == 422
        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.setattr(toolchain, "LOCAL_CPP_BIN", tmp_path / "missing-toolchain")
        response = client.post("/api/debug", json={"code": "int main() {return 0;}", "language": "cpp", "capture_items": 100})
        assert response.status_code == 503
        assert "g++" in response.json()["detail"]


def test_examples_supply_a_runnable_grid_and_every_new_mode():
    with TestClient(app) as client:
        examples = client.get("/api/examples").json()
    grid = next(example for example in examples if example["id"] == "sample7_grid_input.py")
    assert run_debugger(grid["code"], stdin_text=grid["stdin"])["status"] == "completed"
    assert {"sample8_heap.py", "sample9_sliding_window.py", "sample10_monotonic_stack.py", "sample11_fenwick.py", "sample12_kmp.py", "sample13_trie.py"}.issubset({example["id"] for example in examples})
