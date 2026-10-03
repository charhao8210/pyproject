from app.tracer import trace_code


def test_basic_trace_and_stdout() -> None:
    result = trace_code("a = 3\nb = 5\nc = a + b\nprint(c)\n")

    assert result["status"] == "completed"
    assert any(step["line"] == 3 and step["event"] == "line" for step in result["steps"])
    assert result["steps"][-1]["stdout"] == "8\n"
    assert result["steps"][-1]["locals"]["c"]["value"] == 8


def test_function_call_is_recorded() -> None:
    result = trace_code("def add_one(x):\n    y = x + 1\n    return y\n\na = add_one(3)\n")

    call = next(step for step in result["steps"] if step["event"] == "call")
    assert call["function"] == "add_one"
    assert call["locals"]["x"]["value"] == 3
    assert [frame["function"] for frame in call["stack"]] == ["<module>", "add_one"]


def test_recursion_builds_call_stack() -> None:
    source = """\
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

answer = factorial(5)
"""
    result = trace_code(source)

    deepest = max(result["steps"], key=lambda step: len(step["stack"]))
    assert len(deepest["stack"]) == 6
    assert result["steps"][-1]["locals"]["answer"]["value"] == 120


def test_unhandled_exception_is_the_last_step() -> None:
    result = trace_code("a = [10, 20]\nprint(a[5])\n")

    assert result["status"] == "exception"
    assert result["steps"][-1]["event"] == "exception"
    assert result["steps"][-1]["line"] == 2
    assert result["steps"][-1]["exception"]["type"] == "IndexError"
    assert result["steps"][-1]["locals"]["a"]["type"] == "list"


def test_step_limit_stops_execution() -> None:
    result = trace_code("i = 0\nwhile True:\n    i += 1\n", max_steps=12)

    assert result["status"] == "step_limit"
    assert len(result["steps"]) == 12
    assert result["steps"][-1]["event"] == "stopped"
    assert "step limit" in result["steps"][-1]["exception"]["message"]


def test_stdout_is_cumulative() -> None:
    result = trace_code("for i in range(3):\n    print(i)\n")
    stdout_states = [step["stdout"] for step in result["steps"]]

    assert "" in stdout_states
    assert "0\n" in stdout_states
    assert "0\n1\n" in stdout_states
    assert stdout_states[-1] == "0\n1\n2\n"

