import httpx
import asyncio

from app.cpp_runner import compiler_issues
from app.main import app
from app.runner import run_debugger
from app.tracer import MAX_RECORDED_FRAMES, MAX_RECURSION_DEPTH


def _post(payload: dict) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/api/debug", json=payload)

    return asyncio.run(send())


def test_infinite_recursion_is_a_runtime_error_at_the_recursive_call() -> None:
    result = run_debugger("def f(n):\n    return f(n + 1)\n\nf(0)\n")

    assert result["status"] == "exception"
    assert result["error"]["type"] == "RecursionError"
    last = result["steps"][-1]
    assert last["event"] == "exception"
    assert last["line"] == 2
    assert last["depth"] == MAX_RECURSION_DEPTH + 1
    # Deep stacks keep only the outermost frame plus the innermost ones.
    assert len(last["stack"]) == MAX_RECORDED_FRAMES
    assert last["stack"][0]["function"] == "<module>"


def test_recursion_tree_survives_trimmed_deep_stacks() -> None:
    result = run_debugger("def f(n):\n    if n == 0:\n        return 0\n    return f(n - 1)\n\nf(60)\n")

    nodes = result["algorithm"]["recursion_tree"]["nodes"]
    assert len(nodes) == 62
    assert [node["parent"] for node in nodes[1:]] == list(range(0, 61))
    assert nodes[-1]["label"] == "f(0)"


def test_calls_are_numbered_in_order_and_the_root_has_no_number() -> None:
    result = run_debugger("def f(n):\n    if n < 2:\n        return n\n    return f(n - 1) + f(n - 2)\n\nx = f(3)\n")

    nodes = result["algorithm"]["recursion_tree"]["nodes"]
    assert [node["order"] for node in nodes] == [None, 1, 2, 3, 4, 5]


def test_syntax_errors_report_the_line() -> None:
    response = _post({"language": "python", "code": "for i in range(3)\n    print(i)\n", "stdin": ""})

    assert response.status_code == 422
    issue = response.json()["detail"]["issues"][0]
    assert issue["line"] == 1


def test_compiler_errors_are_parsed_into_lines() -> None:
    output = (
        "<user_code.cpp>: In function 'int main()':\n"
        "<user_code.cpp>:3:1: error: expected primary-expression before '}' token\n"
        "<user_code.cpp>:5:9: fatal error: missing.h: No such file or directory\n"
        "<user_code.cpp>:2:5: warning: unused variable 'y'\n"
    )

    assert compiler_issues(output) == [
        {"line": 3, "column": 1, "message": "expected primary-expression before '}' token"},
        {"line": 5, "column": 9, "message": "missing.h: No such file or directory"},
    ]


def test_usage_marks_names_on_the_line_and_values_changed_by_the_previous_line() -> None:
    source = "a = 1\nb = a + 1\nc = [a, b]\n"
    result = run_debugger(source)

    usage = [(step["line"], step["usage"]) for step in result["steps"]]
    line_two = next(entry for line, entry in usage if line == 2)
    line_three = next(entry for line, entry in usage if line == 3)
    assert line_two == {"line": ["a"], "changed": ["a"]}
    assert set(line_three["line"]) == {"a", "b"}
    assert line_three["changed"] == ["b"]


def test_assignment_from_a_call_counts_as_changed_after_the_call_returns() -> None:
    source = "def f():\n    return 5\n\nx = f()\ny = 0\n"
    result = run_debugger(source)

    after_call = next(step for step in result["steps"] if step["line"] == 5)
    assert "x" in after_call["usage"]["changed"]
