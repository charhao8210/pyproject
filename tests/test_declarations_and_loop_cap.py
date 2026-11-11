"""C++ values declared without one, and loop lines switched off after the stop limit."""

import shutil
from pathlib import Path

import pytest

from app.runner import run_debugger

requires_cpp = pytest.mark.skipif(
    not (shutil.which("g++") and shutil.which("gdb")),
    reason="g++ and gdb are required for C++ tracing tests",
)



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
