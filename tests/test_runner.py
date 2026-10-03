import pytest
import shutil

from app.runner import _recover_timeout, run_debugger
from app.validator import SourceValidationError


requires_cpp = pytest.mark.skipif(
    not shutil.which("g++") or not shutil.which("gdb"),
    reason="C++ toolchain unavailable",
)


def _plain(value: dict):
    if value["type"] == "list":
        return [_plain(item) for item in value["items"]]
    if value["type"] == "dict":
        return {entry["key"]["value"]: _plain(entry["value"]) for entry in value["entries"]}
    return value.get("value")


def test_runner_uses_subprocess() -> None:
    result = run_debugger("value = [1, 2, 3]\nprint(value)\n")

    assert result["status"] == "completed"
    assert result["steps"][-1]["stdout"] == "[1, 2, 3]\n"


def test_stdin_supports_input_builtin() -> None:
    result = run_debugger(
        "name = input()\ncount = int(input())\nprint(name, count)\n",
        stdin_text="Ada\n3\n",
    )

    assert result["status"] == "completed"
    assert result["stdin"] == "Ada\n3\n"
    assert result["steps"][-1]["stdout"] == "Ada 3\n"


def test_stdin_supports_restricted_sys_module() -> None:
    result = run_debugger(
        "import sys\ndata = sys.stdin.read().split()\nprint(len(data))\n",
        stdin_text="one two three\n",
    )

    assert result["status"] == "completed"
    assert result["steps"][-1]["stdout"] == "3\n"


def test_stdin_supports_binary_buffer() -> None:
    result = run_debugger(
        "import sys\ndata = sys.stdin.buffer.read().split()\nprint(int(data[0]) * 2)\n",
        stdin_text="21\n",
    )

    assert result["status"] == "completed"
    assert result["steps"][-1]["stdout"] == "42\n"


def test_timeout() -> None:
    result = run_debugger("total = sum(range(1_000_000_000))\n", timeout_seconds=0.05)

    assert result["status"] == "timeout"
    assert result["steps"]
    assert result["steps"][-1]["event"] == "stopped"
    assert result["steps"][-1]["exception"]["type"] == "TimeoutError"


def test_timeout_recovery_appends_exactly_one_terminal_step() -> None:
    checkpoint = [
        {"step": 0, "event": "line", "line": 1, "locals": {}},
        {"step": 1, "event": "return", "line": 2, "locals": {}, "return_value": {"type": "int", "value": 3}},
    ]

    steps, status, error = _recover_timeout([dict(step) for step in checkpoint], 0.5)

    assert status == "timeout"
    assert error["type"] == "TimeoutError"
    assert [step["event"] for step in steps] == ["line", "return", "stopped"]
    assert steps[-1]["step"] == 2
    assert "return_value" not in steps[-1]


def test_timeout_recovery_keeps_existing_step_limit_terminal_step() -> None:
    limit = {"type": "StepLimitExceeded", "message": "Execution stopped: step limit exceeded"}
    checkpoint = [
        {"step": 0, "event": "line", "line": 1},
        {"step": 1, "event": "stopped", "line": 1, "exception": limit},
    ]

    steps, status, error = _recover_timeout(checkpoint, 0.5)

    assert status == "step_limit"
    assert error == limit
    assert [step["event"] for step in steps] == ["line", "stopped"]


@pytest.mark.parametrize("statement", ["import os", "from os import path"])
def test_forbidden_import(statement: str) -> None:
    with pytest.raises(SourceValidationError):
        run_debugger(statement)


@pytest.mark.skipif(not shutil.which("g++") or not shutil.which("gdb"), reason="C++ toolchain unavailable")
def test_cpp_runner_traces_locals_and_stdout() -> None:
    result = run_debugger(
        """#include <iostream>
int twice(int value) {
    int answer = value * 2;
    return answer;
}
int main() {
    int number;
    std::cin >> number;
    int result = twice(number);
    std::cout << result << '\\n';
    return 0;
}
""",
        language="cpp",
        stdin_text="9\n",
    )

    assert result["status"] == "completed"
    assert result["language"] == "cpp"
    assert result["steps"][-1]["stdout"] == "18\n"
    assert any(step["function"] == "twice" for step in result["steps"])
    assert any("answer" in step["locals"] for step in result["steps"])


@pytest.mark.skipif(not shutil.which("g++") or not shutil.which("gdb"), reason="C++ toolchain unavailable")
def test_cpp_runner_expands_repeated_native_array_values() -> None:
    result = run_debugger(
        """#include <iostream>
int main() {
    int n = 3;
    int a[10] = {3, 1, 2};
    std::cout << n << '\\n';
    return 0;
}
""",
        language="cpp",
    )

    arrays = [step["locals"].get("a") for step in result["steps"] if "a" in step["locals"]]
    assert arrays
    assert arrays[-1]["type"] == "list"
    assert [item["value"] for item in arrays[-1]["items"]] == [3, 1, 2, 0, 0, 0, 0, 0, 0, 0]


@pytest.mark.skipif(not shutil.which("g++") or not shutil.which("gdb"), reason="C++ toolchain unavailable")
def test_cpp_runner_decodes_std_vector_for_array_visualization() -> None:
    result = run_debugger(
        """#include <algorithm>
#include <iostream>
#include <vector>
using namespace std;
int main() {
    int n = 4;
    vector<int> a = {8, 2, 5, 1};
    sort(a.begin(), a.end());
    cout << a[0] << '\\n';
    return 0;
}
""",
        language="cpp",
    )

    ready = [step["visualization"] for step in result["steps"] if step["visualization"].get("ready")]
    assert ready
    assert ready[-1]["renderer"] == "array"
    assert ready[-1]["values"] == [1, 2, 5, 8]


@pytest.mark.skipif(not shutil.which("g++") or not shutil.which("gdb"), reason="C++ toolchain unavailable")
def test_cpp_sum_of_three_values_uses_three_sum_visualization() -> None:
    result = run_debugger(
        """#include <algorithm>
#include <vector>
using namespace std;
int main() {
    int n = 5, x = 12;
    vector<int> a = {2, 7, 5, 1, 4};
    sort(a.begin(), a.end());
    for (int i = 0; i < n; ++i) {
        int l = i + 1, r = n - 1;
        while (l < r) {
            int sum = a[i] + a[l] + a[r];
            if (sum == x) return 0;
            if (sum < x) ++l; else --r;
        }
    }
    return 0;
}
""",
        language="cpp",
    )

    assert result["algorithm"]["kind"] == "three_sum"
    assert any(step["visualization"].get("ready") for step in result["steps"])


@pytest.mark.skipif(not shutil.which("g++") or not shutil.which("gdb"), reason="C++ toolchain unavailable")
def test_cpp_timeout_preserves_partial_trace() -> None:
    result = run_debugger(
        """int main() {
    int counter = 0;
    while (true) {
        ++counter;
    }
}
""",
        language="cpp",
        # GDB alone needs about 0.3 s to reach the first stop.
        timeout_seconds=1.0,
    )

    assert result["status"] == "timeout"
    assert len(result["steps"]) > 1
    assert result["steps"][-1]["event"] == "stopped"
    assert result["steps"][-1]["exception"]["type"] == "TimeoutError"


@pytest.mark.skipif(not shutil.which("g++") or not shutil.which("gdb"), reason="C++ toolchain unavailable")
def test_cpp_nested_vector_produces_graph_visualization() -> None:
    result = run_debugger(
        """#include <stack>
#include <vector>
using namespace std;
int main() {
    vector<vector<int>> graph(4);
    graph[1].push_back(2);
    graph[2].push_back(1);
    graph[2].push_back(3);
    graph[3].push_back(2);
    vector<int> visited(4, 0);
    stack<int> frontier;
    frontier.push(1);
    while (!frontier.empty()) {
        int node = frontier.top();
        frontier.pop();
        if (visited[node]) continue;
        visited[node] = 1;
        for (int neighbor : graph[node]) frontier.push(neighbor);
    }
    return 0;
}
""",
        language="cpp",
    )

    assert result["algorithm"]["renderer"] == "graph"
    ready = [step["visualization"] for step in result["steps"] if step["visualization"].get("ready")]
    assert ready
    assert set(ready[-1]["nodes"]) == {"1", "2", "3"}
    assert set(ready[-1]["visited"]) == {"1", "2", "3"}


@requires_cpp
def test_cpp_vector_scopes_never_abort_the_trace() -> None:
    result = run_debugger(
        """#include <iostream>
#include <vector>
using namespace std;
typedef vector<int> vi;
vi build(int n) {
    vi out;
    for (int i = 0; i < n; ++i) out.push_back(i * i);
    return out;
}
int total(const vector<int>& values) {
    int s = 0;
    for (int value : values) s += value;
    return s;
}
int main() {
    int flag = 0;
    if (flag) {
        vector<int> hidden(3, 7);
        flag = hidden[0];
    } else {
        flag = 2;
    }
    vector<bool> seen(5);
    seen[1] = true;
    vector<int> squares = build(4);
    int answer = total(squares);
    cout << answer + flag << '\\n';
    return 0;
}
""",
        language="cpp",
    )

    assert result["status"] == "completed"
    assert result["steps"][-1]["stdout"] == "16\n"
    assert result["steps"][-1]["line"] == 28
    main_locals = result["steps"][-1]["locals"]
    assert _plain(main_locals["seen"]) == [False, True, False, False, False]
    assert _plain(main_locals["squares"]) == [0, 1, 4, 9]
    assert "hidden" not in main_locals
    in_total = [step for step in result["steps"] if step["function"] == "total"]
    assert in_total and _plain(in_total[-1]["locals"]["values"]) == [0, 1, 4, 9]


@requires_cpp
def test_cpp_cses_sum_of_three_values_with_pair_vector() -> None:
    result = run_debugger(
        """#include <bits/stdc++.h>
using namespace std;
int main() {
    int n; long long x;
    cin >> n >> x;
    vector<pair<long long, int>> a(n);
    for (int i = 0; i < n; i++) { cin >> a[i].first; a[i].second = i + 1; }
    sort(a.begin(), a.end());
    for (int i = 0; i < n; i++) {
        int l = i + 1, r = n - 1;
        while (l < r) {
            long long s = a[i].first + a[l].first + a[r].first;
            if (s == x) { cout << a[i].second << " " << a[l].second << " " << a[r].second << "\\n"; return 0; }
            if (s < x) l++; else r--;
        }
    }
    cout << "IMPOSSIBLE\\n";
}
""",
        language="cpp",
        stdin_text="4 8\n2 7 5 1\n",
    )

    assert result["status"] == "completed"
    assert result["algorithm"]["kind"] == "three_sum"
    assert result["steps"][-1]["stdout"] == "4 1 3\n"
    ready = [step["visualization"] for step in result["steps"] if step["visualization"].get("ready")]
    assert ready[-1]["values"] == [1, 2, 5, 7]
    assert ready[-1]["labels"] == [4, 1, 3, 2]
    windows = [view for view in ready if view.get("interval")]
    assert windows and {marker["label"] for marker in windows[-1]["markers"]} >= {"i", "l", "r"}
    assert {"label": "x", "value": 8} in windows[-1]["readouts"]
    assert any(readout["label"] == "s" for readout in windows[-1]["readouts"])


@requires_cpp
def test_cpp_global_adjacency_array_and_visited_flags() -> None:
    result = run_debugger(
        """#include <bits/stdc++.h>
using namespace std;
int n, m;
vector<int> adj[100005];
bool vis[100005];
void dfs(int u) {
    vis[u] = true;
    for (int v : adj[u])
        if (!vis[v]) dfs(v);
}
int main() {
    cin >> n >> m;
    for (int i = 0; i < m; ++i) {
        int a, b;
        cin >> a >> b;
        adj[a].push_back(b);
        adj[b].push_back(a);
    }
    dfs(1);
    cout << count(vis, vis + n + 1, true) << '\\n';
}
""",
        language="cpp",
        stdin_text="4 2\n1 2\n2 3\n",
    )

    assert result["status"] == "completed"
    assert result["algorithm"]["name"] == "Depth-first search · recursive"
    assert result["steps"][-1]["stdout"] == "3\n"
    in_dfs = [step for step in result["steps"] if step["function"] == "dfs"]
    assert in_dfs and in_dfs[-1]["globals"]["n"] == {"type": "int", "value": 4}
    graph = [step["visualization"] for step in result["steps"] if step["visualization"].get("ready")][-1]
    assert set(graph["nodes"]) == {"1", "2", "3", "4"}
    assert set(graph["visited"]) == {"1", "2", "3"}


@requires_cpp
def test_cpp_runtime_error_keeps_unbuffered_output_per_step() -> None:
    result = run_debugger(
        """#include <iostream>
using namespace std;
int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    int* p = nullptr;
    cout << "before" << '\\n';
    int marker = 1;
    *p = marker;
    return 0;
}
""",
        language="cpp",
    )

    assert result["status"] == "exception"
    assert result["error"]["type"] == "SIGSEGV"
    final = result["steps"][-1]
    assert final["event"] == "exception" and final["line"] == 9
    assert final["stdout"] == "before\n"
    marker_step = next(step for step in result["steps"] if step["line"] == 8)
    assert marker_step["stdout"] == "before\n"


@requires_cpp
def test_cpp_uncaught_exception_reports_its_type() -> None:
    result = run_debugger(
        """#include <vector>
int main() {
    std::vector<int> values(3);
    int item = values.at(5);
    return item;
}
""",
        language="cpp",
    )

    assert result["status"] == "exception"
    assert result["error"]["type"] == "std::out_of_range"
    assert result["steps"][-1]["line"] == 4


@requires_cpp
def test_cpp_large_global_arrays_are_sliced_instead_of_failing() -> None:
    result = run_debugger(
        """#include <cstring>
char grid[3][8];
long long dp[1005][1005];
int main() {
    int big[100000] = {};
    big[2] = 7;
    strcpy(grid[0], "..#..");
    dp[1][2] = 5;
    int done = big[2];
    return done - 7;
}
""",
        language="cpp",
    )

    assert result["status"] == "completed"
    final = result["steps"][-1]
    assert final["locals"]["done"] == {"type": "int", "value": 7}
    assert _plain(final["globals"]["grid"]) == ["..#..", "", ""]
    dp = final["globals"]["dp"]
    assert dp["truncated"] is True and len(dp["items"]) == 30
    assert _plain(dp)[1][:3] == [0, 0, 5]
