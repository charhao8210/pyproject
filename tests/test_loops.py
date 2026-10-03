import shutil

import pytest

from app.loops import loop_ranges
from app.runner import run_debugger

requires_cpp = pytest.mark.skipif(
    not shutil.which("g++") or not shutil.which("gdb"),
    reason="C++ toolchain unavailable",
)


def _jumps(result: dict) -> list[tuple[int, object]]:
    return [
        (step["line"], step["loop"] and (step["loop"]["line"], step["loop"]["before"], step["loop"]["after"]))
        for step in result["steps"]
    ]


def test_cpp_loop_ranges_cover_headers_bodies_and_do_while() -> None:
    source = (
        "int main() {\n"
        "    int i = 0;\n"
        "    do {\n"
        "        i++;\n"
        "    } while (i < 3);\n"
        "    for (int a = 0; a < 2; a++)\n"
        "        i++;\n"
        "    while (i) i--;\n"
        "}\n"
    )

    assert [(loop.first_line, loop.last_line) for loop in loop_ranges(source, "cpp")] == [(3, 5), (6, 7), (8, 8)]


def test_python_skip_leaves_the_innermost_loop_then_the_outer_one() -> None:
    result = run_debugger(
        "total = 0\n"
        "for i in range(2):\n"
        "    for j in range(2):\n"
        "        total += j\n"
        "    total += i\n"
        "print(total)\n"
    )
    steps = result["steps"]

    inner = next(index for index, step in enumerate(steps) if step["line"] == 4)
    after_inner = steps[inner]["loop"]["after"]
    assert steps[after_inner]["line"] == 5
    assert steps[steps[inner]["loop"]["before"]]["line"] == 2
    after_outer = steps[after_inner]["loop"]["after"]
    assert steps[after_outer]["line"] == 6
    assert steps[0]["loop"] is None and steps[after_outer]["loop"] is None


@requires_cpp
def test_cpp_skip_from_a_nested_loop_lands_on_the_next_run_then_leaves_the_outer_loop() -> None:
    result = run_debugger(
        "int main() {\n"
        "    int k = 0;\n"
        "    for (int i = 0; i < 3; i++) {\n"
        "        for (int j = 0; j < 2; j++) {\n"
        "            k++;\n"
        "        }\n"
        "    }\n"
        "    return k;\n"
        "}\n",
        language="cpp",
    )
    steps = result["steps"]

    body = next(index for index, step in enumerate(steps) if step["line"] == 5)
    after_inner = steps[body]["loop"]["after"]
    # GDB stops on the inner header once per run: that stop starts the next run.
    assert steps[after_inner]["line"] == 4
    assert steps[body]["loop"]["before"] == body - 1
    after_outer = steps[after_inner]["loop"]["after"]
    assert steps[after_outer]["line"] == 8
