import pytest

from app.runner import run_debugger
from app.toolchain import resolve_cpp_toolchain


compiler, debugger, _ = resolve_cpp_toolchain()
pytestmark = pytest.mark.skipif(not compiler or not debugger, reason="C++ toolchain unavailable")


def test_nonexecutable_global_declaration_does_not_stop_breakpoint_discovery():
    result = run_debugger(
        "#include <iostream>\n"
        "int answer;\n"
        "int main() {\n"
        "    answer = 7;\n"
        "    std::cout << answer << '\\n';\n"
        "    return 0;\n"
        "}\n",
        language="cpp",
    )

    assert result["status"] == "completed"
    assert len(result["steps"]) > 1
    assert any(step["line"] == 4 for step in result["steps"])
    assert result["steps"][-1]["globals"]["answer"]["value"] == 7
    # GDB's auto-load diagnostics must not appear as user-program output.
    assert result["steps"][-1]["stdout"] == "7\n"


def test_caught_cpp_exception_continues_without_an_execution_error():
    result = run_debugger(
        "#include <iostream>\n"
        "#include <stdexcept>\n"
        "int main() {\n"
        "    try { throw std::runtime_error(\"caught\"); }\n"
        "    catch (const std::exception &error) { std::cout << error.what() << '\\n'; }\n"
        "    return 0;\n"
        "}\n",
        language="cpp",
    )

    assert result["status"] == "completed"
    assert result["error"] is None
    assert result["steps"][-1]["stdout"] == "caught\n"
