"""3D arrays drawn two layers at a time, and C++ values declared without one."""

import shutil
from pathlib import Path

import pytest

from app.cpp_runner import _serialize_cube
from app.cpp_source import classify_type, cube_layer_index
from app.runner import run_debugger

requires_cpp = pytest.mark.skipif(
    not (shutil.which("g++") and shutil.which("gdb")),
    reason="g++ and gdb are required for C++ tracing tests",
)


def test_a_3d_array_of_numbers_is_read_as_a_cube() -> None:
    # The element type tells the program's `pvdbg_pack` how to write the values.
    assert classify_type("long long", 3, {}) == ("cube", "", "long long")
    assert classify_type("bool", 3, {}) == ("cube", "", "bool")
    assert classify_type("char", 3, {}) is None
    assert cube_layer_index("dp[i][j][k] = dp[i - 1][j][k];", "dp") == ("i", "i")
    assert cube_layer_index("dp[i + 1][j][k] += dp[i][j][k];", "dp") == ("i", "i + 1")
    assert cube_layer_index("if (dp[i][j][k] == 1) ans++;", "dp") is None


def test_a_cube_block_is_split_back_into_rows() -> None:
    value = _serialize_cube("@cube 4 3 3\n@layer 0\n{0 <repeats 9 times>}\n@layer 1\n{1, 2, 3, 0, 0, 0, 0, 0, 5}\n", "::dp")
    assert value["type"] == "cube" and value["length"] == 4
    assert [layer["index"] for layer in value["layers"]] == [0, 1]
    rows = [[cell["value"] for cell in row["items"]] for row in value["layers"][1]["value"]["items"]]
    assert rows == [[1, 2, 3], [0, 0, 0], [0, 0, 5]]


def test_packed_corners_are_split_into_layers_and_rows() -> None:
    # `pvdbg_pack` wrote layers 1 and 2, two used rows of three used columns each.
    value = _serialize_cube("@cube 4 30 30\n@pack 1 2 2 3\n{1, 2, 3, 0, 0, 4, 5, 6, 7, 0, 0, -8}", "::dp")
    layers = {layer["index"]: [[cell["value"] for cell in row["items"]] for row in layer["value"]["items"]] for layer in value["layers"]}
    assert layers == {1: [[1, 2, 3], [0, 0, 4]], 2: [[5, 6, 7], [0, 0, -8]]}
    assert value["layers"][0]["value"]["truncated"] is True


@requires_cpp
def test_floating_and_bool_3d_arrays_are_written_by_kind() -> None:
    code = (
        "#include <bits/stdc++.h>\nusing namespace std;\ndouble p[3][2][2];\nbool seen[3][2][2];\nint main() {\n"
        "    for (int i = 1; i < 3; i++) {\n        p[i][1][1] = p[i - 1][1][1] + 0.5;\n        seen[i][0][1] = true;\n    }\n"
        "    return 0;\n}\n"
    )
    final = run_debugger(code, language="cpp")["steps"][-1]["globals"]
    p_layers = {layer["index"]: layer["value"]["items"] for layer in final["p"]["layers"]}
    assert p_layers[2][1]["items"][1]["value"] == 1.0
    seen_layers = {layer["index"]: layer["value"]["items"] for layer in final["seen"]["layers"]}
    assert seen_layers[2][0]["items"][1] == {"type": "bool", "value": True}


CUBE_PROGRAM = """#include <bits/stdc++.h>
using namespace std;
int dp[4][3][3];
int main() {
    for (int i = 1; i <= 2; i++) {
        for (int j = 0; j < 3; j++) {
            for (int k = 0; k < 3; k++) {
                dp[i][j][k] = dp[i - 1][j][k] + j + k;
            }
        }
    }
    return 0;
}
"""


@requires_cpp
def test_a_3d_dp_draws_the_layer_it_reads_beside_the_layer_it_writes() -> None:
    result = run_debugger(CUBE_PROGRAM, language="cpp")
    assert result["status"] == "completed"
    assert result["algorithm"]["name"] == "Dynamic programming · 3D table"
    assert result["algorithm"]["auto_renderer"] == "layers"
    step = next(
        step for step in result["steps"]
        if step["line"] == 8 and step["locals"]["i"]["value"] == 2
        and step["locals"]["j"]["value"] == 1 and step["locals"]["k"]["value"] == 2
    )
    view = step["visualization"]
    assert view["renderer"] == "layers" and view["name"] == "dp"
    assert [layer["index"] for layer in view["layers"]] == [1, 2]
    assert view["current"] == [{"layer": 2, "row": 1, "column": 2}]
    assert view["reading"] == [{"layer": 1, "row": 1, "column": 2}]
    # Drawn after the line ran: dp[2][1][2] = dp[1][1][2] + 3 = 3 + 3.
    assert view["layers"][1]["rows"][1][2] == 6
    assert {"layer": 2, "row": 1, "column": 2} in view["written"]
    assert "reads dp[1][1][2] = 3" in view["details"] and "writes dp[2][1][2]" in view["details"]
    assert {"dp", "i", "j", "k"} <= set(view["uses"])
    # Only the used part is drawn: 3 rows × 3 columns.
    assert len(view["layers"][0]["rows"]) == 3 and len(view["layers"][0]["rows"][0]) == 3


@requires_cpp
def test_a_value_declared_without_one_appears_where_it_is_read() -> None:
    # `int n, m, ans = 0;` used to list n with the garbage its memory held.
    code = (
        "#include <bits/stdc++.h>\nusing namespace std;\nint main() {\n"
        "    int n, m, ans = 0;\n    cin >> n >> m;\n    ans = n + m;\n    cout << ans;\n    return 0;\n}\n"
    )
    steps = run_debugger(code, language="cpp", stdin_text="3 4\n")["steps"]
    declaring = next(step for step in steps if step["line"] == 4)
    reading = next(step for step in steps if step["line"] == 5)
    assert set(declaring["usage"]["appearing"]) == {"ans"}
    assert {name: entry["value"]["value"] for name, entry in reading["usage"]["appearing"].items()} == {"n": 3, "m": 4}
    assert {"n", "m"} <= set(reading["usage"]["new"])


def test_the_page_draws_3d_tables() -> None:
    root = Path(__file__).resolve().parents[1] / "app"
    script = (root / "static" / "app.js").read_text(encoding="utf-8")
    terms = (root / "static" / "terms.js").read_text(encoding="utf-8")
    assert "function renderLayersAlgorithm(" in script and "layers: renderLayersAlgorithm" in script
    assert "function renderCubeValue(" in script
    assert 'term: "Writing"' in terms and 'term: "3D table"' in terms


@requires_cpp
def test_loop_lines_stop_being_traced_after_the_limit_and_the_program_finishes(monkeypatch) -> None:
    from app import cpp_runner

    monkeypatch.setattr(cpp_runner, "MAX_LOOP_LINE_STOPS", 20)
    code = (
        "#include <bits/stdc++.h>\nusing namespace std;\nint a[100];\nint main() {\n"
        "    long long s = 0;\n    for (int i = 0; i < 60; i++) {\n        a[i] = i;\n        s += a[i];\n    }\n"
        "    cout << s << endl;\n    return 0;\n}\n"
    )
    result = run_debugger(code, language="cpp")
    assert result["status"] == "completed"
    assert result["loop_stop_limit"] == 20
    assert sorted(entry["line"] for entry in result["capped"]) == [7, 8]
    assert sum(step["line"] == 7 for step in result["steps"]) == 20
    # Values the switched-off lines kept writing are read again afterwards, not cached.
    final = result["steps"][-1]
    assert final["stdout"] == "1770\n"
    assert final["locals"]["s"]["value"] == 1770
    assert [item["value"] for item in final["globals"]["a"]["items"][:50]] == list(range(50))


def test_the_page_explains_switched_off_loop_lines() -> None:
    root = Path(__file__).resolve().parents[1] / "app"
    script = (root / "static" / "app.js").read_text(encoding="utf-8")
    assert "function cappedNote(" in script and "loop_stop_limit" in script
