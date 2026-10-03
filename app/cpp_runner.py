from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .analyzer import analyze_execution
from .cpp_source import (
    TREE_KINDS,
    SourceModel,
    ValueSpec,
    analyze_source,
    classify_type,
    strip_code,
    template_arguments,
)
from .serializer import is_zero, trailing_fill


CPP_FILENAME = "program.cpp"
PRELUDE_FILENAME = "pvdbg_prelude.hpp"
EXECUTABLE_NAME = "program.exe" if os.name == "nt" else "program"
BEGIN_MARKER = "__PVDBG_BEGIN__"
ARGS_MARKER = "__PVDBG_ARGS__"
LOCALS_MARKER = "__PVDBG_LOCALS__"
STACK_MARKER = "__PVDBG_STACK__"
END_MARKER = "__PVDBG_END__"
LIMIT_MARKER = "__PVDBG_STEP_LIMIT__"
VECTOR_MARKER = "__PVDBG_VECTOR__"
GLOBAL_MARKER = "__PVDBG_GLOBAL__"
VECTOR_END_MARKER = "__PVDBG_VECTOR_END__"
SCOPE_MARKER = "__PVDBG_SCOPE__"
SCOPE_END_MARKER = "__PVDBG_SCOPE_END__"
TYPE_MARKER = "__PVDBG_TYPE__"
TAIL_MARKER = "@tail"
TABLE_MARKER = "@rows"
HEAP_MARKER = "@heap"
CHAR_TABLE_MARKER = "@chars"
# Printed instead of a global that no line has touched since the previous stop.
SAME_VALUE = "@same"
MAX_VALUE_ITEMS = 50
MAX_TABLE_ROWS = 30
MAX_TABLE_COLUMNS = 40
UNREADABLE_VALUES = ("<optimized out>", "<unavailable>", "<error")
# Static initialization and atexit destructor thunks attribute their code to
# global declaration lines; they are not user execution steps.
COMPILER_GENERATED_FUNCTION = re.compile(
    r"^(?:__static_initialization_and_destruction_\d+|_GLOBAL__sub_I_|__tcf_\d+|__cxx_global_var_init)"
)

# Force stdout to be unbuffered so output appears at the step that produced it
# and survives a crash or timeout. It is injected with `-include`, so user line
# numbers are unchanged.
UNBUFFERED_OUTPUT_PRELUDE = """#include <cstdio>
#include <iostream>

namespace {
struct PvdbgUnbufferedOutput {
    PvdbgUnbufferedOutput() {
        std::setvbuf(stdout, nullptr, _IONBF, 0);
        std::cout.setf(std::ios::unitbuf);
    }
} pvdbg_unbuffered_output;
}

// Called from GDB: the size of a buffer up to and including its last nonzero byte.
extern "C" __attribute__((used, noinline, optimize("O2")))
unsigned long long pvdbg_used_bytes(const unsigned char *data, unsigned long long size) {
    while (size > 0 && data[size - 1] == 0) --size;
    return size;
}
"""


@dataclass
class _Discovery:
    break_lines: list[int] = field(default_factory=list)
    # Local names GDB reports in scope at each breakpoint. A missing entry means
    # the scope is unknown, so no extraction commands are generated there.
    scopes: dict[int, frozenset[str]] = field(default_factory=dict)
    global_specs: list[ValueSpec] = field(default_factory=list)
    # Lines whose breakpoint has several locations; one can sit in another line's code.
    multi_location: set[int] = field(default_factory=set)


class CppCompilationError(ValueError):
    def __init__(self, output: str) -> None:
        super().__init__(output)
        self.issues = compiler_issues(output)


_COMPILER_ERROR = re.compile(
    r"^<user_code\.cpp>:(\d+):(\d+):\s*(?:fatal\s+)?error:\s*(.+)$",
    re.MULTILINE,
)


def compiler_issues(output: str) -> list[dict[str, str | int]]:
    """Pull `file:line:column: error: message` entries out of g++ output."""
    return [
        {"line": int(line), "column": int(column), "message": message.strip()}
        for line, column, message in _COMPILER_ERROR.findall(output)
    ]


class CppToolchainError(RuntimeError):
    pass


class CppExecutionTimeoutError(TimeoutError):
    pass


def run_cpp_debugger(
    source: str,
    *,
    stdin_text: str = "",
    timeout_seconds: float = 3.0,
    max_steps: int = 5_000,
) -> dict[str, Any]:
    compiler = shutil.which("g++")
    debugger = shutil.which("gdb")
    if not compiler or not debugger:
        missing = "g++" if not compiler else "gdb"
        raise CppToolchainError(
            f"C++ debugging requires {missing} to be installed and available on PATH."
        )
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if max_steps < 1:
        raise ValueError("max_steps must be at least 1")

    model = analyze_source(source)
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        with tempfile.TemporaryDirectory(
            prefix="visual-debugger-cpp-",
            ignore_cleanup_errors=True,
        ) as directory:
            workdir = Path(directory)
            source_path = workdir / CPP_FILENAME
            executable_path = workdir / EXECUTABLE_NAME
            source_path.write_text(source, encoding="utf-8")
            (workdir / PRELUDE_FILENAME).write_text(UNBUFFERED_OUTPUT_PRELUDE, encoding="utf-8")
            (workdir / "input.txt").write_text(stdin_text, encoding="utf-8")

            _compile_source(
                compiler,
                source_path,
                executable_path,
                workdir,
                creation_flags,
            )
            discovery = _discover(
                debugger,
                executable_path,
                source,
                model,
                workdir,
                creation_flags,
            )
            trace_output, trace_errors, timed_out = _run_trace(
                debugger,
                executable_path,
                discovery.break_lines,
                _extraction_plan(model, discovery, source),
                max_steps,
                timeout_seconds,
                workdir,
                creation_flags,
            )
    except subprocess.TimeoutExpired as error:
        raise CppExecutionTimeoutError(
            f"C++ execution exceeded the {timeout_seconds:g} second timeout."
        ) from error

    steps, stdout, incomplete_line = _parse_trace(trace_output, model)
    status, error = _execution_status(trace_output, trace_errors)
    if timed_out:
        status = "timeout"
        error = {
            "type": "TimeoutError",
            "message": f"C++ execution exceeded the {timeout_seconds:g} second timeout.",
        }
    elif LIMIT_MARKER in trace_output:
        status = "step_limit"
        error = {
            "type": "StepLimitExceeded",
            "message": "Execution stopped: step limit exceeded",
        }
    elif incomplete_line is not None and status == "completed":
        status = "exception"
        error = _debugger_error(incomplete_line, trace_errors)
    if steps:
        steps[-1]["stdout"] = stdout
        if error:
            steps[-1]["exception"] = error
            steps[-1]["event"] = "exception" if status == "exception" else "stopped"
    elif stdout or error:
        steps.append(
            {
                "step": 0,
                "event": "exception" if error else "return",
                "filename": "<user_code.cpp>",
                "function": "<program>",
                "line": 1,
                "locals": {},
                "globals": {},
                "stack": [],
                "stdout": stdout,
                **({"exception": error} if error else {}),
            }
        )

    result = {
        "source": source,
        "stdin": stdin_text,
        "language": "cpp",
        "steps": steps,
        "status": status,
        "error": error,
    }
    result["algorithm"] = analyze_execution(source, steps, language="cpp")
    return result


def _compile_source(
    compiler: str,
    source_path: Path,
    executable_path: Path,
    workdir: Path,
    creation_flags: int,
) -> None:
    completed = subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-g",
            "-O0",
            "-fno-omit-frame-pointer",
            "-include",
            PRELUDE_FILENAME,
            str(source_path.name),
            "-o",
            str(executable_path.name),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=12,
        cwd=workdir,
        creationflags=creation_flags,
        check=False,
    )
    if completed.returncode == 0:
        return
    detail = completed.stderr.strip() or completed.stdout.strip() or "Compilation failed."
    detail = detail.replace(str(source_path), "<user_code.cpp>")
    detail = detail.replace(source_path.name, "<user_code.cpp>")
    raise CppCompilationError(detail[:12_000])


def _discover(
    debugger: str,
    executable_path: Path,
    source: str,
    model: SourceModel,
    workdir: Path,
    creation_flags: int,
) -> _Discovery:
    """Find breakpoint lines, DWARF scopes, and the types of namespace-scope variables."""
    candidates = _candidate_lines(source)
    if not candidates:
        return _Discovery()
    commands = [
        "set pagination off",
        "set confirm off",
        "set breakpoint pending off",
        "set print thread-events off",
        "set width 0",
    ]
    for line in candidates:
        commands.extend(
            [
                f"break {CPP_FILENAME}:{line}",
                # A multi-location breakpoint is reported under the requested line even when
                # GDB moved it to a later one (a global declaration slides into the next
                # function); the listing names the real line.
                "info breakpoints $bpnum",
                f"echo {SCOPE_MARKER}{line}\\n",
                f"info scope {CPP_FILENAME}:{line}",
                f"echo {SCOPE_END_MARKER}\\n",
            ]
        )
    script_path = workdir / "discover.gdb"
    script_path.write_text("\n".join(commands) + "\n", encoding="utf-8")
    # Each -ex command is isolated: an unknown name only fails its own whatis.
    type_queries: list[str] = []
    for candidate in model.globals:
        type_queries.extend(
            ["-ex", f"echo {TYPE_MARKER}{candidate.name}\\n", "-ex", f"whatis {candidate.name}"]
        )
    completed = subprocess.run(
        [
            debugger,
            "-q",
            "-batch",
            "-x",
            script_path.name,
            *type_queries,
            executable_path.name,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=8,
        cwd=workdir,
        creationflags=creation_flags,
        check=False,
    )
    output = completed.stdout
    source_line_count = len(source.splitlines())

    break_pattern = re.compile(
        rf"Breakpoint\s+\d+\s+at\s+[^\n]*?(?:file\s+{re.escape(CPP_FILENAME)},\s+line\s+(\d+)"
        rf"|{re.escape(CPP_FILENAME)}:(\d+)\.\s+\(\d+\s+locations\))",
        re.IGNORECASE,
    )
    scope_pattern = re.compile(
        rf"{SCOPE_MARKER}(\d+)\r?\n(.*?){SCOPE_END_MARKER}",
        re.DOTALL,
    )
    discovery = _Discovery()
    break_lines: set[int] = set()
    cursor = 0
    for match in scope_pattern.finditer(output):
        segment = output[cursor : match.start()]
        resolved = break_pattern.findall(segment)
        cursor = match.end()
        if not resolved:
            continue
        located = re.search(rf"\bat\s+{re.escape(CPP_FILENAME)}:(\d+)\s*$", segment, re.MULTILINE)
        line = int(located.group(1)) if located else int(resolved[-1][0] or resolved[-1][1])
        if not 1 <= line <= source_line_count:
            continue
        break_lines.add(line)
        if resolved[-1][1]:
            discovery.multi_location.add(line)
        body = match.group(2)
        if "Scope for" in body or "no locals" in body.lower():
            names = frozenset(re.findall(r"^Symbol\s+([A-Za-z_]\w*)\s+is\b", body, re.MULTILINE))
            discovery.scopes[line] = discovery.scopes.get(line, frozenset()) | names
    discovery.break_lines = sorted(break_lines)

    types = dict(
        re.findall(rf"{TYPE_MARKER}([A-Za-z_]\w*)\r?\ntype = ([^\r\n]+)", output)
    )
    for candidate in model.globals:
        type_text = types.get(candidate.name)
        if not type_text:
            continue
        dimensions = re.search(r"(?:\s*\[\d*\])+\s*$", type_text)
        base = type_text[: dimensions.start()] if dimensions else type_text
        dimension_count = dimensions.group(0).count("[") if dimensions else 0
        classified = classify_type(base, dimension_count, model.aliases)
        if classified is None:
            continue
        kind, element, row_type = classified
        discovery.global_specs.append(
            ValueSpec(
                name=candidate.name,
                kind=kind,
                element=element,
                row_type=row_type if model.raw_casts or kind in TREE_KINDS else "",
                declaration_line=candidate.declaration_line,
                ready_line=candidate.declaration_line,
            )
        )
    return discovery


def _candidate_lines(source: str) -> list[int]:
    candidates: list[int] = []
    for line_number, raw_line in enumerate(strip_code(source).split("\n"), start=1):
        line = raw_line.strip()
        if (
            not line
            or line.startswith(("using ", "namespace ", "template"))
            or re.fullmatch(r"[{};]+", line)
        ):
            continue
        candidates.append(line_number)
    return candidates


def _extraction_plan(
    model: SourceModel,
    discovery: _Discovery,
    source: str,
) -> dict[int, list[str]]:
    """Generate the value-extraction commands that are safe at each breakpoint.

    `plan[0]` holds setup commands that run once before the program starts.
    """
    plan: dict[int, list[str]] = {}
    # Reading a global is the slow part of a stop (GDB loops over table rows, and the
    # zero-tail scan is an inferior call), so each global is re-read only after a line
    # that names it has run, or after any line of a function that could alias it
    # through an array, pointer, or reference parameter. Other stops print `@same`.
    code = strip_code(source)
    code_lines = code.split("\n")
    aliasing_lines = _aliasing_function_lines(code, model)
    alias_names = _alias_variables(code)
    # Local containers are cached the same way, plus their address: another call of the
    # function (recursion, a sibling call) holds a different object under the same name.
    # Parameters, range-for variables, and references are always re-read: they can name a
    # different object at the same address, or one written under another name.
    local_cached = {
        spec.name
        for spec in model.vectors
        if _cacheable_local(spec, code_lines, alias_names)
    } - {
        spec.name
        for spec in model.vectors
        if not _cacheable_local(spec, code_lines, alias_names)
    }
    cached = [
        *(f"$pv_dirty_{spec.name}" for spec in discovery.global_specs),
        *(f"$pv_ldirty_{name}" for name in sorted(local_cached)),
    ]
    plan[0] = [
        *(f"set {flag} = 1" for flag in cached),
        *(f"set {flag.replace('dirty_', 'wsp_')} = 0" for flag in cached),
        *(f"set $pv_laddr_{name} = 0" for name in sorted(local_cached)),
    ]
    # `m[k]` inserts into a map, so only these containers are read by a subscript.
    subscript_reads = {spec.name for spec in (*discovery.global_specs, *model.vectors) if spec.kind in INDEXED_KINDS} - {
        spec.name for spec in (*discovery.global_specs, *model.vectors) if spec.kind not in INDEXED_KINDS
    }
    # Functions and lambdas a statement can call (or hand to `sort`); an `operator<` can be
    # entered from any container call, so then every writing statement counts.
    user_functions = sorted(
        {
            *re.findall(r"\b([A-Za-z_]\w*)\s*\([^()]*\)\s*(?:const\s*)?\{", code),
            *re.findall(r"\b([A-Za-z_]\w*)\s*=\s*\[[^\]]*\]\s*\(", code),
        }
        - {"if", "for", "while", "switch", "catch", "main"}
    )
    user_operators = bool(re.search(r"\boperator\b", code))
    # Values some calling statement writes: only their reads compare stack pointers.
    sticky_flags: set[str] = set()
    alias_blocks = {
        alias: {
            model.block_for_line(number)
            for number, text in enumerate(code_lines, start=1)
            if re.search(rf"[&*]\s*{re.escape(alias)}\s*[=:]|\bauto\s+{re.escape(alias)}\s*=|[&*]\s*\[[^\]]*\b{re.escape(alias)}\b", text)
        }
        or {None}
        for alias in alias_names
    }
    alias_targets = {alias: _alias_targets(code, alias) for alias in alias_names}
    lines = discovery.break_lines
    for position, line in enumerate(lines):
        # A statement can continue past its breakpoint line, up to the next breakpoint.
        following = lines[position + 1] if position + 1 < len(lines) else line + 1
        statement = " ".join(code_lines[line - 1 : max(line, following - 1)])
        block = model.block_for_line(line)
        if line in discovery.multi_location and block is not None:
            # A second location can sit inside another line's code (a range-for in a
            # lambda stops "on line 13" while running line 14), so any write in the
            # function may have happened since the previous stop.
            start, end = model.function_blocks[block]
            statement = " ".join(code_lines[start - 1 : end])
        # `cin >> x` with `for (auto &x : a)`, or `*p = 1`, writes a global under another name.
        # An alias only counts in the function declaring it: `place(int row)` is not `auto &row`.
        aliased = [
            alias_targets[alias]
            for alias, blocks in alias_blocks.items()
            if (None in blocks or block in blocks) and re.search(rf"(?<![\w.]){re.escape(alias)}\b", statement)
        ]
        # It writes what it was bound to (`Edge &e = edges[id]` → `edges`), or anything
        # when a call produced it.
        through_alias = {name for targets in aliased if targets is not None for name in targets}
        alias_to_all = any(targets is None for targets in aliased)
        # Only a statement that can stop inside user code before it finishes needs the
        # mark to survive those stops; elsewhere it would re-read a recursion's whole subtree.
        # Static initialisation (lines outside every function) runs in a frame above
        # `main`, so a mark made there would never clear.
        sticky = block is not None and (
            user_operators or bool(user_functions and re.search(rf"\b(?:{'|'.join(user_functions)})\b", statement))
        )
        marked = [
            flag
            for flag in cached
            if line in aliasing_lines
            or alias_to_all
            or flag.split("dirty_", 1)[1] in through_alias
            or _may_write(statement, flag.split("dirty_", 1)[1], flag.split("dirty_", 1)[1] in subscript_reads)
        ]
        if sticky:
            sticky_flags.update(marked)
        plan[line] = [command for flag in marked for command in _mark_dirty(flag, sticky)]
    for line in discovery.break_lines:
        scope = discovery.scopes.get(line)
        if scope is None:
            continue
        visible: dict[str, ValueSpec] = {}
        for spec in model.vectors:
            if spec.name not in scope or not spec.visible_at(line):
                continue
            current = visible.get(spec.name)
            if current is None or spec.declaration_line > current.declaration_line:
                visible[spec.name] = spec
        commands: list[str] = []
        for spec in visible.values():
            commands.extend(
                _value_commands(
                    VECTOR_MARKER,
                    spec,
                    cached=spec.name in local_cached,
                    sticky=f"$pv_ldirty_{spec.name}" in sticky_flags,
                )
            )
        for spec in discovery.global_specs:
            if spec.name not in scope and spec.visible_at(line):
                commands.extend(
                    _value_commands(GLOBAL_MARKER, spec, cached=True, sticky=f"$pv_dirty_{spec.name}" in sticky_flags)
                )
        # Marking runs after extraction: the line itself executes after this stop.
        plan[line] = commands + plan[line]
    return plan


def _mark_dirty(flag: str, sticky: bool = True) -> list[str]:
    """Mark a cached value for re-reading until its statement has finished.

    `inv[n] = power(x)` stops inside `power` before the assignment: a read there must not
    clear the mark. `$pv_wsp_*` keeps the outermost marking frame's stack pointer, and a
    read clears the mark only from that frame or a shallower one (the stack grows down).
    """
    if not sticky:
        return [f"set {flag} = 1"]
    wsp = flag.replace("dirty_", "wsp_")
    return [
        f"set {flag} = 1",
        f"set {wsp} = {wsp} > (long long) $sp ? {wsp} : (long long) $sp",
    ]


def _clear_dirty(flag: str, sticky: bool = True) -> list[str]:
    if not sticky:
        return [f"set {flag} = 0"]
    wsp = flag.replace("dirty_", "wsp_")
    return [
        f"set {flag} = (long long) $sp < {wsp}",
        f"set {wsp} = {flag} ? {wsp} : 0",
    ]


# Calls and keywords whose parenthesised arguments are only read.
READ_ONLY_CALLS = frozenset({
    "if", "while", "for", "switch", "return", "max", "min", "abs", "llabs", "labs", "fabs",
    "__gcd", "gcd", "lcm", "sqrt", "sqrtl", "pow", "powl", "log", "log2", "printf", "puts",
    "putchar", "__builtin_popcount", "__builtin_popcountll", "__builtin_ctz", "__builtin_clz",
    "to_string", "",
})
# Members that only read their container (`a.size()`), unless the result is assigned to.
READ_ONLY_MEMBERS = frozenset({
    "size", "empty", "length", "count", "top", "front", "back", "find", "lower_bound", "upper_bound",
})
_SUBSCRIPTS = r"(?:\s*\[(?:[^\[\]]|\[(?:[^\[\]]|\[[^\[\]]*\])*\])*\])*"


INDEXED_KINDS = frozenset({"array", "matrix", "vector", "nested", "bits", "vector_array", "string", "deque"})


def _may_write(statement: str, name: str, subscript_reads: bool = True) -> bool:
    """Whether a statement can change `name`; reading it (`d[x][y] != -1`) cannot.

    Any occurrence that is not plainly read counts as a write: assignment, `++`/`--`,
    `cin >>`, `&name`, a member call other than a read-only one, or an argument of a
    call that could take it by reference (`swap(a[i], a[j])`, `sort(a, a + n)`).
    """
    for match in re.finditer(rf"(?<![\w.]){re.escape(name)}\b(?!\s*::)", statement):
        before = statement[: match.start()].rstrip()
        rest = statement[match.end():]
        subscripts = re.match(_SUBSCRIPTS, rest)
        after = rest[subscripts.end():].lstrip()
        if subscripts.group(0) and not subscript_reads:
            return True
        if re.match(r"(?:[-+*/%^|&]|<<|>>)?=(?!=)|\+\+|--", after):
            return True
        if before.endswith(("++", "--", "&", ">>")) and not before.endswith("&&"):
            return True
        # A declaration (`vector<int> d(n);`, `int a[5];`) creates the object.
        word = re.search(r"([A-Za-z_]\w*)$", before)
        if (before.endswith(">") and not before.endswith("->")) or (
            word and word.group(1) not in {"return", "else", "case", "do", "throw"}
        ):
            return True
        # `(d % 2 ? white : black).push_back(x)`: the group's result is written.
        if _enclosing_call(before) == "" and re.match(
            r"\s*(?:\.|->|\[|(?:[-+*/%^|&]|<<|>>)?=(?!=)|\+\+|--)", _after_group(after)
        ):
            return True
        member = re.match(r"(?:(?:\.|->)\s*\w+\s*)+", after)
        if member:
            tail = after[member.end():]
            last = re.findall(r"\w+", member.group(0))[-1]
            if tail.startswith("("):
                # A method call: only a few never change their object.
                if last not in READ_ONLY_MEMBERS or re.match(r"\([^()]*\)\s*(?:(?:[-+*/%^|&]|<<|>>)?=(?!=)|\+\+|--)", tail):
                    return True
            elif re.match(r"(?:[-+*/%^|&]|<<|>>)?=(?!=)|\+\+|--|\[", tail):
                # `e[i].cap -= 1`, `p.first++`, or a subscripted member.
                return True
            elif before.endswith(("(", ",")) and _enclosing_call(before) not in READ_ONLY_CALLS:
                return True
            continue
        if before.endswith(("(", ",")) and _enclosing_call(before) not in READ_ONLY_CALLS:
            return True
    return False


def _enclosing_call(before: str) -> str | None:
    """The function or keyword whose argument list is still open at the end of `before`."""
    depth = 0
    for position in range(len(before) - 1, -1, -1):
        character = before[position]
        if character == ")":
            depth += 1
        elif character == "(":
            if depth == 0:
                callee = re.search(r"([A-Za-z_]\w*)\s*$", before[:position])
                return callee.group(1) if callee else ""
            depth -= 1
    # A top-level comma: the next declarator of `vector<int> p(n), q(n);`.
    return None


def _after_group(rest: str) -> str:
    """The text after the parenthesis that closes the group `rest` starts inside."""
    depth = 0
    for position, character in enumerate(rest):
        if character == "(":
            depth += 1
        elif character == ")":
            if depth == 0:
                return rest[position + 1 :]
            depth -= 1
    return ""


ALIAS_SAFE_CALLS = frozenset({"begin", "end", "rbegin", "rend", "find", "lower_bound", "upper_bound", "back", "front", "top", "data", "at"})


def _alias_targets(code: str, alias: str) -> frozenset[str] | None:
    """Names an alias can point into: every expression it is bound or reassigned to.

    None (anything) when one of them calls a function, which could return any reference.
    """
    targets: set[str] = set()
    # `auto &[u, v] : edges` binds `u` through the whole bracket.
    pattern = rf"(?<![\w.]){re.escape(alias)}\s*(?:,[\w\s,]*)?(?:\]\s*)?(?:=(?!=)|:(?!:))([^;]*)"
    if not re.search(pattern, code):
        return None
    for match in re.finditer(pattern, code):
        expression = match.group(1)
        calls = set(re.findall(r"\b([A-Za-z_]\w*)\s*\(", expression))
        if calls - ALIAS_SAFE_CALLS - {"for", "if", "while"}:
            return None
        targets.update(re.findall(r"\b[A-Za-z_]\w*\b", expression))
    return frozenset(targets)


def _cacheable_local(spec: ValueSpec, code_lines: list[str], alias_names: set[str]) -> bool:
    if spec.parameter or spec.name in alias_names:
        return False
    declaration = code_lines[spec.declaration_line - 1] if 0 < spec.declaration_line <= len(code_lines) else ""
    return not re.search(rf"[&*]\s*{re.escape(spec.name)}\b", declaration)


def _alias_variables(code: str) -> set[str]:
    """Names of non-const references, pointers, and iterators that may write into a global."""
    names: set[str] = set()
    # `auto &x : a`, `int &r = a[i]`, `auto &[u, v] : edges` (but not `const auto &x`).
    for match in re.finditer(r"(?:^|[;{}(])\s*(const\s+)?[\w:<>, ]*?&\s*(\[[^\]]*\]|[A-Za-z_]\w*)\s*[=:]", code, re.M):
        if match.group(1):
            continue
        names.update(re.findall(r"[A-Za-z_]\w*", match.group(2)))
    # `int *p = &a[2]`, `long long *row = grid[i]`.
    names.update(re.findall(r"\b(?:int|long|char|bool|double|float|short|unsigned|auto)\b[\w\s]*\*\s*([A-Za-z_]\w*)\s*=", code))
    # Iterators can write too: `auto it = v.begin(); *it = 3;`.
    names.update(re.findall(r"\bauto\s+([A-Za-z_]\w*)\s*=\s*[^;]*\b(?:begin|end|find|lower_bound|upper_bound)\s*\(", code))
    return names


def _aliasing_function_lines(code: str, model: SourceModel) -> set[int]:
    """Lines of functions taking an array, pointer, or reference parameter."""
    starts = {start: end for start, end in model.function_blocks}
    lines: set[int] = set()
    for match in re.finditer(r"\b[A-Za-z_]\w*\s*\(([^()]*)\)\s*(?:const\s*)?\{", code):
        if not re.search(r"[\[*&]", match.group(1)):
            continue
        brace_line = code.count("\n", 0, match.end() - 1) + 1
        if brace_line in starts:
            lines.update(range(brace_line, starts[brace_line] + 1))
    return lines


def _run_trace(
    debugger: str,
    executable_path: Path,
    break_lines: list[int],
    plan: dict[int, list[str]],
    max_steps: int,
    timeout_seconds: float,
    workdir: Path,
    creation_flags: int,
) -> tuple[str, str, bool]:
    commands = [
        "set pagination off",
        "set confirm off",
        "set breakpoint pending off",
        "set print thread-events off",
        "set print pretty off",
        f"set print elements {MAX_VALUE_ITEMS}",
        "set print repeats unlimited",
        "set print null-stop on",
        "set width 0",
        "set $pv_steps = 0",
        *plan.get(0, []),
    ]
    for line in break_lines:
        commands.extend(
            [
                f"break {CPP_FILENAME}:{line}",
                "commands",
                "silent",
                "set $pv_steps = $pv_steps + 1",
                f"if $pv_steps > {max_steps}",
                f"echo {LIMIT_MARKER}\\n",
                "kill",
                "quit",
                "end",
                f"echo {BEGIN_MARKER}\\n",
                "frame",
                f"echo {ARGS_MARKER}\\n",
                "info args",
                f"echo {LOCALS_MARKER}\\n",
                "info locals",
                *plan.get(line, []),
                f"echo {STACK_MARKER}\\n",
                "backtrace 30",
                f"echo {END_MARKER}\\n",
                "continue",
                "end",
            ]
        )
    commands.append("run < input.txt")
    script_path = workdir / "trace.gdb"
    script_path.write_text("\n".join(commands) + "\n", encoding="utf-8")
    try:
        completed = subprocess.run(
            [debugger, "-q", "-batch", "-x", script_path.name, executable_path.name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            cwd=workdir,
            creationflags=creation_flags,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        return (
            _decode_timeout_output(error.stdout),
            _decode_timeout_output(error.stderr),
            True,
        )
    return completed.stdout, completed.stderr, False


def _decode_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _value_commands(marker: str, spec: ValueSpec, cached: bool = False, sticky: bool = True) -> list[str]:
    name = spec.name
    commands: list[str] = []
    if spec.kind == "vector":
        commands.extend(_sequence_commands(name, MAX_VALUE_ITEMS))
    elif spec.kind == "bits":
        commands.extend(_bits_commands(name, MAX_VALUE_ITEMS))
    elif spec.kind == "nested":
        commands.extend(
            _table_commands(
                f"{name}._M_impl._M_start",
                f"{name}._M_impl._M_finish - {name}._M_impl._M_start",
                spec,
            )
        )
    elif spec.kind == "vector_array":
        commands.extend(
            _table_commands(f"&{name}[0]", f"sizeof({name}) / sizeof({name}[0])", spec)
        )
    elif spec.kind == "string":
        commands.append(f"output (const char *) {name}._M_dataplus._M_p")
    elif spec.kind == "array":
        commands.extend(_native_array_commands(name, spec))
    elif spec.kind == "matrix":
        commands.extend(_native_matrix_commands(name, spec))
    elif spec.kind in {"deque", "queue", "stack"}:
        storage = name if spec.kind == "deque" else f"{name}.c"
        commands.extend(_deque_commands(storage, spec.kind, MAX_VALUE_ITEMS))
    elif spec.kind in TREE_KINDS:
        commands.extend(_tree_commands(name, spec.kind, spec.row_type.split("|"), MAX_VALUE_ITEMS))
    elif spec.kind == "priority_queue":
        commands.extend([f"echo {HEAP_MARKER}\\n", *_sequence_commands(f"{name}.c", MAX_VALUE_ITEMS)])
    else:
        commands.append(f"output {name}")
    if cached and marker == VECTOR_MARKER:
        address = f"(long long) &{name}"
        commands = [
            f"if $pv_ldirty_{name} || $pv_laddr_{name} != {address}",
            *commands,
            *_clear_dirty(f"$pv_ldirty_{name}", sticky),
            f"set $pv_laddr_{name} = {address}",
            "else",
            f"echo {SAME_VALUE}",
            "end",
        ]
    elif cached:
        commands = [
            f"if $pv_dirty_{name}",
            *commands,
            *_clear_dirty(f"$pv_dirty_{name}", sticky),
            "else",
            f"echo {SAME_VALUE}",
            "end",
        ]
    return [f"echo {marker}{name}\\n", *commands, f"echo \\n{VECTOR_END_MARKER}\\n"]


def _native_array_commands(name: str, spec: ValueSpec) -> list[str]:
    # Print a bounded slice: `output name` would load the whole array, and GDB
    # refuses values larger than max-value-size (64 KiB) with a fatal error.
    commands = [
        f"set $pv_total = sizeof({name}) / sizeof({name}[0])",
        f"set $pv_len = $pv_total > {MAX_VALUE_ITEMS} ? {MAX_VALUE_ITEMS} : $pv_total",
        f"output *&{name}[0]@$pv_len",
    ]
    if spec.element != "text":
        commands.extend(
            [
                f"if $pv_total > {MAX_VALUE_ITEMS}",
                "echo ...",
                "end",
                # Contest code declares arrays far larger than the input (`dis[100005]`).
                # A native helper from the prelude finds the last nonzero byte, so the UI
                # can say the unread rest is all zero without GDB reading every element.
                f"if $pv_total > {MAX_VALUE_ITEMS}",
                f"set $pv_used = pvdbg_used_bytes((const unsigned char *) &{name}[0], sizeof({name}))",
                f'printf "\\n{TAIL_MARKER} %d %d", ($pv_used + sizeof({name}[0]) - 1) / sizeof({name}[0]), $pv_total',
                "end",
            ]
        )
    return commands


def _tree_commands(name: str, kind: str, types: list[str], limit: int) -> list[str]:
    """Print a libstdc++ set/map as `@<kind> <size>` and one element per line, in order.

    Walks the red-black tree like `_Rb_tree_increment`: the value sits right after the
    node header (`sizeof(*$pv_n)`), read through a cast to the declared element type.
    """
    address = "(char *) $pv_n + sizeof(*$pv_n)"
    element = _typed_output(f"pair<{types[0]},{types[1]}>", address) if len(types) == 2 else _typed_output(types[0], address)
    return [
        f"set $pv_total = {name}._M_t._M_impl._M_node_count",
        f'printf "@{kind} %d", $pv_total',
        f"set $pv_left = $pv_total > {limit} ? {limit} : $pv_total",
        f"set $pv_n = {name}._M_t._M_impl._M_header._M_left",
        "while $pv_left > 0",
        "echo \\n",
        *element,
        "if $pv_n->_M_right != 0",
        "set $pv_n = $pv_n->_M_right",
        "while $pv_n->_M_left != 0",
        "set $pv_n = $pv_n->_M_left",
        "end",
        "else",
        "set $pv_y = $pv_n->_M_parent",
        "while $pv_n == $pv_y->_M_right",
        "set $pv_n = $pv_y",
        "set $pv_y = $pv_y->_M_parent",
        "end",
        "if $pv_n->_M_right != $pv_y",
        "set $pv_n = $pv_y",
        "end",
        "end",
        "set $pv_left = $pv_left - 1",
        "end",
    ]


def _typed_output(type_text: str, address: str) -> list[str]:
    """GDB commands printing the value of `type_text` stored at `address` (a char pointer)."""
    if type_text.startswith("pair<"):
        first, second = template_arguments(type_text)[:2]
        # `second` starts at the first multiple of its size after `first` (builtin types).
        offset = f"((sizeof({first}) + sizeof({second}) - 1) / sizeof({second})) * sizeof({second})"
        return [
            "echo {first = ",
            f"output *({first} *) ({address})",
            "echo , second = ",
            f"output *({second} *) ({address} + {offset})",
            "echo }",
        ]
    return [f"output *({type_text} *) ({address})"]


def _deque_commands(expression: str, label: str, limit: int) -> list[str]:
    """Print a libstdc++ deque as `@<label> <size>` and one `{values}` line per buffer.

    A deque stores its elements in fixed-size buffers; `_M_node` points into the map
    of buffer pointers, and the start/finish iterators bound the used part.
    """
    return [
        f"set $pv_s = {expression}._M_impl._M_start",
        f"set $pv_f = {expression}._M_impl._M_finish",
        "set $pv_buf = $pv_s._M_last - $pv_s._M_first",
        "set $pv_total = ($pv_f._M_node - $pv_s._M_node - 1) * $pv_buf"
        " + ($pv_f._M_cur - $pv_f._M_first) + ($pv_s._M_last - $pv_s._M_cur)",
        f'printf "@{label} %d", $pv_total',
        f"set $pv_left = $pv_total > {limit} ? {limit} : $pv_total",
        "set $pv_node = $pv_s._M_node",
        "set $pv_p = $pv_s._M_cur",
        "while $pv_left > 0",
        "set $pv_n = *$pv_node + $pv_buf - $pv_p",
        "set $pv_n = $pv_n > $pv_left ? $pv_left : $pv_n",
        "echo \\n",
        "output *$pv_p@$pv_n",
        "set $pv_left = $pv_left - $pv_n",
        "set $pv_node = $pv_node + 1",
        "set $pv_p = *$pv_node",
        "end",
    ]


def _native_matrix_commands(name: str, spec: ValueSpec) -> list[str]:
    # Character rows are printed as codes (`output/d`), not C strings: a 1-indexed grid
    # leaves a[i][0] == '\0', and string printing would stop there and show every row empty.
    # GDB loads a whole row for `name[0]` or `name[row][0]` (even inside sizeof), and a
    # row of `int sp[18][200005]` exceeds max-value-size, which aborts the stop. Rows are
    # therefore reached by pointer arithmetic from &name[0][0], which reads nothing.
    text = spec.element == "text"
    return [
        f"set $pv_rows_total = sizeof({name}) / sizeof(*{name})",
        f"set $pv_rows = $pv_rows_total > {MAX_TABLE_ROWS} ? {MAX_TABLE_ROWS} : $pv_rows_total",
        f"set $pv_total = &{name}[1][0] - &{name}[0][0]",
        f"set $pv_len = $pv_total > {MAX_TABLE_COLUMNS} ? {MAX_TABLE_COLUMNS} : $pv_total",
        f'printf "{CHAR_TABLE_MARKER if text else TABLE_MARKER} %d\\n", $pv_rows_total',
        "set $pv_row = 0",
        "while $pv_row < $pv_rows",
        'printf "%d %d ", $pv_row, $pv_total',
        f"output{'/d' if text else ''} *(&{name}[0][0] + $pv_row * $pv_total)@$pv_len",
        "echo \\n",
        "set $pv_row = $pv_row + 1",
        "end",
    ]


def _sequence_commands(expression: str, limit: int) -> list[str]:
    """Print a std::vector as `{a, b}`, followed by `...` when clipped."""
    start = f"{expression}._M_impl._M_start"
    return [
        f"set $pv_total = {expression}._M_impl._M_finish - {start}",
        f"set $pv_len = $pv_total > {limit} ? {limit} : $pv_total",
        "if $pv_len > 0",
        f"output *{start}@$pv_len",
        "else",
        "echo {}",
        "end",
        f"if $pv_total > {limit}",
        "echo ...",
        "end",
    ]


def _bits_commands(expression: str, limit: int) -> list[str]:
    """Print std::vector<bool> as `@bits <size> <word bits> {words}`."""
    start = f"{expression}._M_impl._M_start._M_p"
    finish = f"{expression}._M_impl._M_finish"
    return [
        f"set $pv_w = (long) (sizeof(*{start}) * 8)",
        f"set $pv_total = ({finish}._M_p - {start}) * $pv_w + {finish}._M_offset",
        f"set $pv_len = $pv_total > {limit} ? {limit} : $pv_total",
        "set $pv_words = ($pv_len + $pv_w - 1) / $pv_w",
        'printf "@bits %d %d ", $pv_total, $pv_w',
        "if $pv_words > 0",
        f"output *{start}@$pv_words",
        "else",
        "echo {}",
        "end",
    ]


def _table_commands(first_row: str, row_count: str, spec: ValueSpec) -> list[str]:
    """Print rows of vectors sparsely: `@rows <count>` then `<row> <size> {values}` lines."""
    commands = [
        f"set $pv_rows_total = {row_count}",
        f"set $pv_rows = $pv_rows_total > {MAX_TABLE_ROWS} ? {MAX_TABLE_ROWS} : $pv_rows_total",
        'printf "@rows %d\\n", $pv_rows_total',
        "set $pv_row = 0",
    ]
    if spec.element == "bits":
        # std::vector<bool> is five pointer-sized words in libstdc++:
        # {start._M_p, start._M_offset, finish._M_p, finish._M_offset, end_of_storage}.
        # The offsets are 32-bit, so the low half of their word holds the value.
        # Row headers are fetched with one read instead of member lookups per row.
        commands.extend(
            [
                "set $pv_w = (long) (sizeof(unsigned long) * 8)",
                "if $pv_rows > 0",
                f"set $pv_hdr = *(char **) ({first_row}) @ (5 * $pv_rows)",
                "end",
                "while $pv_row < $pv_rows",
                "set $pv_bits = (unsigned long *) $pv_hdr[5 * $pv_row]",
                "set $pv_total = ((unsigned long *) $pv_hdr[5 * $pv_row + 2] - $pv_bits) * $pv_w"
                " + (unsigned int) (long long) $pv_hdr[5 * $pv_row + 3]",
                f"set $pv_len = $pv_total > {MAX_TABLE_COLUMNS} ? {MAX_TABLE_COLUMNS} : $pv_total",
                "set $pv_words = ($pv_len + $pv_w - 1) / $pv_w",
                "if $pv_words > 0",
                'printf "%d @bits %d %d ", $pv_row, $pv_total, $pv_w',
                "output *$pv_bits@$pv_words",
                "echo \\n",
                "end",
                "set $pv_row = $pv_row + 1",
                "end",
            ]
        )
        return commands

    print_row = [
        f"set $pv_len = $pv_total > {MAX_TABLE_COLUMNS} ? {MAX_TABLE_COLUMNS} : $pv_total",
        'printf "%d %d ", $pv_row, $pv_total',
        "output *$pv_s@$pv_len",
        "echo \\n",
    ]
    if spec.row_type:
        # Raw libstdc++ layout: each vector is {start, finish, end_of_storage}.
        # Reading every row header with one memory access and skipping empty
        # rows keeps sparse adjacency arrays cheap at every step.
        header = "$pv_hdr[3 * $pv_row]"
        commands.extend(
            [
                "if $pv_rows > 0",
                f"set $pv_hdr = *(char **) ({first_row}) @ (3 * $pv_rows)",
                "end",
                "while $pv_row < $pv_rows",
                f"if {header} < $pv_hdr[3 * $pv_row + 1]",
                f"set $pv_s = ({spec.row_type} *) {header}",
                f"set $pv_total = ({spec.row_type} *) $pv_hdr[3 * $pv_row + 1] - $pv_s",
                *print_row,
                "end",
                "set $pv_row = $pv_row + 1",
                "end",
            ]
        )
        return commands
    commands.extend(
        [
            f"set $pv_rp = {first_row}",
            "while $pv_row < $pv_rows",
            "set $pv_s = $pv_rp[$pv_row]._M_impl._M_start",
            "set $pv_total = $pv_rp[$pv_row]._M_impl._M_finish - $pv_s",
            "if $pv_total > 0",
            *print_row,
            "end",
            "set $pv_row = $pv_row + 1",
            "end",
        ]
    )
    return commands


def _parse_trace(
    output: str,
    model: SourceModel,
) -> tuple[list[dict[str, Any]], str, int | None]:
    """Return steps, program stdout, and the line of an unfinished block, if any."""
    block_pattern = re.compile(
        rf"{BEGIN_MARKER}\r?\n(.*?){END_MARKER}\r?\n?",
        re.DOTALL,
    )
    matches = list(block_pattern.finditer(output))
    steps: list[dict[str, Any]] = []
    captured_stdout = ""
    previous_end: int | None = None
    last_globals: dict[str, str] = {}
    parsed_values: dict[tuple[str, str], dict[str, Any]] = {}

    for match in matches:
        if previous_end is not None:
            captured_stdout += _clean_program_output(output[previous_end : match.start()])
        step = _parse_step_block(
            match.group(1), len(steps), captured_stdout, model, last_globals, parsed_values
        )
        if step is not None:
            steps.append(step)
        previous_end = match.end()

    tail = output[previous_end:] if previous_end is not None else output
    incomplete_line: int | None = None
    partial = tail.find(BEGIN_MARKER)
    if partial >= 0:
        location = re.search(
            rf"#0\s+[^\n]*?at\s+{re.escape(CPP_FILENAME)}:(\d+)",
            tail[partial:],
        )
        incomplete_line = int(location.group(1)) if location else 0
        tail = tail[:partial]
    captured_stdout += _clean_program_output(tail)
    return steps, captured_stdout, incomplete_line


def _parse_step_block(
    block: str,
    index: int,
    stdout: str,
    model: SourceModel,
    last_globals: dict[str, str] | None = None,
    parsed_values: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if ARGS_MARKER not in block or LOCALS_MARKER not in block or STACK_MARKER not in block:
        return None
    header, remainder = block.split(ARGS_MARKER, 1)
    args_text, remainder = remainder.split(LOCALS_MARKER, 1)
    locals_text, stack_text = remainder.split(STACK_MARKER, 1)
    frame_match = re.search(
        rf"#0\s+(?:0x[0-9a-f]+\s+in\s+)?(.+?)\s*\([^\n]*\)\s+at\s+{re.escape(CPP_FILENAME)}:(\d+)",
        header,
        re.IGNORECASE,
    )
    if not frame_match:
        return None
    function_name = frame_match.group(1).strip()
    line = int(frame_match.group(2))

    extracted_locals = _parse_marked_values(locals_text, VECTOR_MARKER)
    extracted_globals = _parse_marked_values(locals_text, GLOBAL_MARKER)
    if last_globals is not None:
        for name, value in list(extracted_globals.items()):
            if value == SAME_VALUE:
                if name in last_globals:
                    extracted_globals[name] = last_globals[name]
                else:
                    del extracted_globals[name]
        last_globals.update(extracted_globals)
        # Cached locals share the dict under a prefix no C++ name can have.
        for name, value in list(extracted_locals.items()):
            if value == SAME_VALUE:
                if f"local:{name}" in last_globals:
                    extracted_locals[name] = last_globals[f"local:{name}"]
                else:
                    del extracted_locals[name]
            else:
                last_globals[f"local:{name}"] = value
    # Static initialisation is not shown, but a global it read is cached from then on.
    if COMPILER_GENERATED_FUNCTION.match(function_name):
        return None
    plain_locals_text = re.sub(
        rf"(?:{VECTOR_MARKER}|{GLOBAL_MARKER}).*?{VECTOR_END_MARKER}",
        "",
        locals_text,
        flags=re.DOTALL,
    )
    arguments = _parse_variables(args_text)
    local_values = {
        name: value
        for name, value in _parse_variables(plain_locals_text).items()
        if _declared_before(model, name, line) and name not in model.line_declarations.get(line, ())
    }
    variables = {**arguments, **local_values, **extracted_locals}
    # Containers mostly repeat unchanged between stops; parsing a table again is the slow part.
    cache = parsed_values if parsed_values is not None else {}
    serialized = {}
    for name, value in variables.items():
        if name == "this":
            continue
        path = f"{function_name}:{name}"
        if name not in extracted_locals:
            serialized[name] = _serialize_cpp_value(value, path)
            continue
        if (path, value) not in cache:
            cache[(path, value)] = _serialize_cpp_value(value, path)
        serialized[name] = cache[(path, value)]
    globals_ = {}
    for name, value in extracted_globals.items():
        if name in serialized:
            continue
        if (name, value) not in cache:
            cache[(name, value)] = _serialize_cpp_value(value, f"::{name}")
        globals_[name] = cache[(name, value)]
    return {
        "step": index,
        "event": "line",
        "filename": "<user_code.cpp>",
        "function": function_name,
        "line": line,
        "locals": serialized,
        "globals": globals_,
        "stack": _parse_stack(stack_text),
        "stdout": stdout,
    }


def _declared_before(model: SourceModel, name: str, line: int) -> bool:
    """Hide GDB locals whose declaration has not executed yet at this line."""
    block = model.block_for_line(line)
    if block is None:
        return True
    first_use = model.first_uses.get(block, {}).get(name)
    return first_use is None or first_use < line


def _parse_variables(text: str) -> dict[str, str]:
    variables: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^([A-Za-z_]\w*)\s*=\s*(.*)$", line.strip())
        if not match:
            continue
        name, value = match.group(1), match.group(2).strip()
        if name.startswith("__") or value.startswith(UNREADABLE_VALUES):
            continue
        # `info locals` lists the innermost declaration first when names are shadowed.
        variables.setdefault(name, value)
    return variables


def _parse_marked_values(text: str, marker: str) -> dict[str, str]:
    pattern = re.compile(
        rf"{marker}([A-Za-z_]\w*)\r?\n(.*?){VECTOR_END_MARKER}",
        re.DOTALL,
    )
    return {
        name: value.strip()
        for name, value in pattern.findall(text)
        if value.strip()
    }


def _parse_stack(text: str) -> list[dict[str, str | int]]:
    frames: list[dict[str, str | int]] = []
    # `args` keeps GDB's argument text so the recursion tree can label calls and tell
    # sibling calls at the same depth apart.
    pattern = re.compile(
        rf"^#\d+\s+(?:0x[0-9a-f]+\s+in\s+)?(.+?)\s*\((.*)\)[^\n]*?\s+at\s+{re.escape(CPP_FILENAME)}:(\d+)",
        re.IGNORECASE,
    )
    for line in text.splitlines():
        match = pattern.search(line.strip())
        if match:
            frames.append({
                "function": match.group(1).strip(),
                "line": int(match.group(3)),
                "args": match.group(2).strip(),
            })
    frames.reverse()
    return frames


def _serialize_cpp_value(value: str, identity: str) -> dict[str, Any]:
    value, tail = _split_tail(value.strip())
    # References (parameters, structured bindings) print as `@0xADDRESS: value`.
    reference = re.match(r"@0x[0-9a-fA-F]+:\s*(.*)\Z", value, re.DOTALL)
    if reference:
        return _serialize_cpp_value(reference.group(1), identity)
    # A pointer into a named object prints as `0xADDRESS <d1+8>`: show what it points at.
    pointer = re.fullmatch(r"(?:\([^()]*\*\)\s*)?0x[0-9a-fA-F]+\s*<([^<>]+)>", value)
    if pointer:
        return {"type": "object", "class_name": "pointer", "value": f"→ {pointer.group(1)}"}
    if value.startswith((TABLE_MARKER, CHAR_TABLE_MARKER)):
        return _serialize_table(value, identity)
    if value.startswith("@bits"):
        return _serialize_bits(value, identity, MAX_VALUE_ITEMS)
    tree = re.match(r"@(set|multiset|map|multimap)\s+(-?\d+)", value)
    if tree:
        return _serialize_tree(value, tree.group(1), int(tree.group(2)), identity)
    if value.startswith(HEAP_MARKER):
        heap = _serialize_cpp_value(value[len(HEAP_MARKER) :], identity)
        return {**heap, "class_name": "priority_queue"} if heap.get("type") == "list" else heap
    deque = re.match(r"@(deque|queue|stack)\s+(-?\d+)", value)
    if deque:
        return _serialize_deque(value, deque.group(1), int(deque.group(2)), identity)
    if value in {"true", "false"}:
        return {"type": "bool", "value": value == "true"}
    if value in {"nullptr", "NULL", "0x0"}:
        return {"type": "none", "value": None}
    if re.fullmatch(r"[-+]?\d+", value):
        return {"type": "int", "value": int(value)}
    if re.fullmatch(r"[-+]?(?:\d+\.\d*|\d*\.\d+)(?:[eE][-+]?\d+)?[fFlL]?", value):
        try:
            return {"type": "float", "value": float(value.rstrip("fFlL"))}
        except ValueError:
            pass
    character = re.fullmatch(r"-?\d+\s+'((?:\\.|[^'\\])*)'", value)
    if character:
        return {"type": "str", "value": _decode_c_string(character.group(1))}
    if len(value) >= 3 and value[0] == "'" and value[-1] == "'":
        return {"type": "str", "value": _decode_c_string(value[1:-1])}
    if re.match(r"^\{(?:static npos = \d+, )?_M_dataplus = ", value):
        string_object = re.search(
            r"_M_p = 0x[0-9a-fA-F]+(?: <[^>]*>)? \"((?:\\.|[^\"\\])*)\"(\.\.\.)?",
            value,
        )
        if string_object:
            return _string_value(string_object.group(1), bool(string_object.group(2)))

    truncated = False
    if value.startswith("{") and value.endswith("}..."):
        value = value[:-3]
        truncated = True
    if value.startswith("{") and value.endswith("}"):
        inner = value[1:-1].strip()
        if inner.endswith("..."):
            inner = inner[:-3]
            truncated = True
        all_parts = _expand_cpp_repeats(_flatten_base_classes(_split_cpp_items(inner)))
        truncated = truncated or len(all_parts) > MAX_VALUE_ITEMS
        parts = all_parts[:MAX_VALUE_ITEMS]
        object_id = zlib.crc32(identity.encode("utf-8"))
        if parts and re.match(r"_M_(?:node|current|cur)\s*=", parts[0]):
            # An iterator holds only a pointer into its container.
            return {"type": "object", "class_name": "iterator", "object_id": object_id, "value": "position in a container"}
        # pb_ds trees (`ordered_set`) print only empty policy base classes.
        if any(part.startswith("_M_") for part in parts) or (
            parts and all(part.startswith("<No data fields>") for part in parts)
        ):
            # Undecoded libstdc++ containers (unordered_map, ...) only expose
            # allocator pointers, which are noise in a teaching view.
            return _opaque_container(object_id)
        named = [re.match(r"^([A-Za-z_]\w*)\s*=\s*(.*)$", part, re.DOTALL) for part in parts]
        if parts and all(named):
            entries = [
                {
                    "key": {"type": "str", "value": match.group(1)},
                    "value": _serialize_cpp_value(match.group(2), f"{identity}.{match.group(1)}"),
                }
                for match in named
                if match is not None
            ]
            # queue, stack, and priority_queue wrap their storage in a member `c`.
            if any(
                entry["key"]["value"] == "c" and entry["value"].get("class_name") == "STL container"
                for entry in entries
            ):
                return _opaque_container(object_id)
            # std::pair reads like a Python tuple: `(3, 1)`, and grid code treats it as a cell.
            if [entry["key"]["value"] for entry in entries] == ["first", "second"]:
                return {
                    "type": "tuple",
                    "object_id": object_id,
                    "items": [entry["value"] for entry in entries],
                }
            return {"type": "dict", "object_id": object_id, "entries": entries}
        items = [
            _serialize_cpp_value(item, f"{identity}[{position}]")
            for position, item in enumerate(parts)
        ]
        length, unread_zero = _zero_tail(tail, items)
        fill = trailing_fill(items, length, unread_zero) if not truncated or unread_zero else None
        return {
            "type": "list",
            "object_id": object_id,
            "items": items,
            **({"truncated": True} if truncated else {}),
            **({"length": length} if unread_zero else {}),
            **({"fill": fill} if fill else {}),
        }
    string_match = re.search(r'"((?:\\.|[^"\\])*)"(\.\.\.)?$', value)
    if string_match:
        return _string_value(string_match.group(1), bool(string_match.group(2)))
    return {
        "type": "object",
        "class_name": "C++ value",
        "object_id": zlib.crc32(identity.encode("utf-8")),
        "value": value[:1_000],
        **({"truncated": True} if len(value) > 1_000 else {}),
    }


def _split_tail(value: str) -> tuple[str, str]:
    """Separate the `@tail {...}` summary that follows a clipped native array."""
    parts = re.split(rf"\r?\n{TAIL_MARKER}\s*", value, maxsplit=1)
    return parts[0].strip(), parts[1].strip() if len(parts) > 1 else ""


def _zero_tail(tail: str, items: list[dict[str, Any]]) -> tuple[int, dict[str, Any] | None]:
    """Return the array length and its zero value when every unread element is zero.

    `tail` is `<used> <total>`: the element count up to the last nonzero byte.
    """
    match = re.fullmatch(r"(\d+)\s+(\d+)", tail)
    if not match or not items or int(match.group(1)) > len(items):
        return len(items), None
    zero = {"type": items[0]["type"], "value": False if items[0]["type"] == "bool" else 0}
    return (int(match.group(2)), zero) if is_zero(zero) else (len(items), None)


def _serialize_deque(value: str, label: str, total: int, identity: str) -> dict[str, Any]:
    parts: list[str] = []
    for chunk in value.splitlines()[1:]:
        chunk = chunk.strip()
        if chunk.startswith("{") and chunk.endswith("}"):
            parts.extend(_split_cpp_items(chunk[1:-1]))
    parts = parts[:MAX_VALUE_ITEMS]
    return {
        "type": "list",
        "class_name": label,
        "object_id": zlib.crc32(identity.encode("utf-8")),
        "items": [
            _serialize_cpp_value(item, f"{identity}[{position}]")
            for position, item in enumerate(parts)
        ],
        **({"truncated": True} if max(total, 0) > len(parts) else {}),
    }


def _serialize_tree(value: str, kind: str, total: int, identity: str) -> dict[str, Any]:
    lines = [line.strip() for line in value.splitlines()[1:] if line.strip()][:MAX_VALUE_ITEMS]
    items = [_serialize_cpp_value(line, f"{identity}[{position}]") for position, line in enumerate(lines)]
    clipped = {"truncated": True} if max(total, 0) > len(items) else {}
    object_id = zlib.crc32(identity.encode("utf-8"))
    if kind in {"map", "multimap"}:
        entries = [
            {"key": item["items"][0], "value": item["items"][1]}
            for item in items
            if item.get("type") == "tuple" and len(item.get("items", [])) == 2
        ]
        return {"type": "dict", "class_name": kind, "object_id": object_id, "entries": entries, **clipped}
    return {"type": "list", "class_name": kind, "object_id": object_id, "items": items, **clipped}


def _opaque_container(object_id: int) -> dict[str, Any]:
    return {
        "type": "object",
        "class_name": "STL container",
        "object_id": object_id,
        "value": "contents not decoded",
    }


def _string_value(body: str, truncated: bool) -> dict[str, Any]:
    return {
        "type": "str",
        "value": _decode_c_string(body),
        **({"truncated": True} if truncated else {}),
    }


def _decode_c_string(body: str) -> str:
    escapes = {
        "n": 10, "t": 9, "r": 13, "a": 7, "b": 8, "f": 12, "v": 11, "e": 27,
        "\\": 92, '"': 34, "'": 39, "?": 63,
    }
    decoded = bytearray()
    position = 0
    while position < len(body):
        character = body[position]
        if character != "\\" or position + 1 >= len(body):
            decoded.extend(character.encode("utf-8"))
            position += 1
            continue
        following = body[position + 1]
        if following in "01234567":
            end = position + 1
            while end < len(body) and end < position + 4 and body[end] in "01234567":
                end += 1
            decoded.append(int(body[position + 1 : end], 8) & 0xFF)
            position = end
        elif following == "x":
            digits = re.match(r"[0-9a-fA-F]{1,2}", body[position + 2 :])
            if digits:
                decoded.append(int(digits.group(0), 16))
                position += 2 + len(digits.group(0))
            else:
                decoded.extend(b"x")
                position += 2
        else:
            decoded.append(escapes.get(following, ord(following) if ord(following) < 128 else 63))
            position += 2
    return decoded.decode("utf-8", errors="replace").rstrip("\x00")


def _serialize_bits(value: str, identity: str, limit: int) -> dict[str, Any]:
    match = re.match(r"@bits\s+(-?\d+)\s+(\d+)\s*(\{.*\})?", value, re.DOTALL)
    items: list[dict[str, Any]] = []
    total = 0
    if match:
        total = max(0, int(match.group(1)))
        width = max(1, int(match.group(2)))
        words = [int(word) for word in re.findall(r"-?\d+", match.group(3) or "")]
        for position in range(min(total, limit)):
            word_index = position // width
            if word_index >= len(words):
                break
            items.append({"type": "bool", "value": bool((words[word_index] >> (position % width)) & 1)})
    return {
        "type": "list",
        "object_id": zlib.crc32(identity.encode("utf-8")),
        "items": items,
        **({"truncated": True} if total > len(items) else {}),
    }


def _serialize_table(value: str, identity: str) -> dict[str, Any]:
    lines = value.splitlines()
    chars = lines[0].startswith(CHAR_TABLE_MARKER)
    header = re.match(r"@(?:rows|chars)\s+(-?\d+)", lines[0])
    total = max(0, int(header.group(1))) if header else 0
    row_count = min(total, MAX_TABLE_ROWS)
    rows: list[dict[str, Any] | None] = [None] * row_count
    for line in lines[1:]:
        row_match = re.match(r"^(\d+)\s+(.*)$", line.strip())
        if not row_match or int(row_match.group(1)) >= row_count:
            continue
        row_index = int(row_match.group(1))
        row_identity = f"{identity}[{row_index}]"
        remainder = row_match.group(2)
        if remainder.startswith("@bits"):
            rows[row_index] = _serialize_bits(remainder, row_identity, MAX_TABLE_COLUMNS)
            continue
        sized = re.match(r"^(-?\d+)\s+(.*)$", remainder)
        if not sized:
            continue
        row = _serialize_cpp_value(sized.group(2), row_identity)
        if chars:
            row = _char_row(row)
        if int(sized.group(1)) > MAX_TABLE_COLUMNS:
            row["truncated"] = True
        rows[row_index] = row
    return {
        "type": "list",
        "object_id": zlib.crc32(identity.encode("utf-8")),
        "items": [
            row
            if row is not None
            else {"type": "str", "value": ""}
            if chars
            else {
                "type": "list",
                "object_id": zlib.crc32(f"{identity}[{position}]".encode("utf-8")),
                "items": [],
            }
            for position, row in enumerate(rows)
        ],
        **({"truncated": True} if total > row_count else {}),
    }


def _char_row(row: dict[str, Any]) -> dict[str, Any]:
    """Character codes of one row as a string; NUL stays in place so columns keep their index."""
    codes = [item.get("value") for item in row.get("items", [])]
    text = "".join(chr(code & 0xFF) if isinstance(code, int) and code else "\0" for code in codes)
    return {"type": "str", "value": text.rstrip("\0")}


def _flatten_base_classes(parts: list[str]) -> list[str]:
    """Inline libstdc++ base-class subobjects such as `<std::__pair_base<...>> = {...}`."""
    flattened: list[str] = []
    for part in parts:
        if part == "<No data fields>":
            continue
        base = re.match(r"^<.*>\s*=\s*\{(.*)\}$", part, re.DOTALL)
        if base:
            flattened.extend(_flatten_base_classes(_split_cpp_items(base.group(1))))
        else:
            flattened.append(part)
    return flattened


def _split_cpp_items(value: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    escaped = False
    for index, character in enumerate(value):
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {'"', "'"}:
            quote = character
        elif character in "{[(<":
            depth += 1
        elif character in "}])>":
            depth = max(0, depth - 1)
        elif character == "," and depth == 0:
            parts.append(value[start:index].strip())
            start = index + 1
    tail = value[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _expand_cpp_repeats(parts: list[str]) -> list[str]:
    expanded: list[str] = []
    repeat_pattern = re.compile(r"^(.*?)\s*<repeats\s+(\d+)\s+times>$")
    for part in parts:
        match = repeat_pattern.match(part)
        if not match:
            expanded.append(part)
            continue
        count = min(int(match.group(2)), MAX_VALUE_ITEMS + 1 - len(expanded))
        expanded.extend([match.group(1).strip()] * max(0, count))
        if len(expanded) > MAX_VALUE_ITEMS:
            break
    return expanded


def _clean_program_output(text: str) -> str:
    text = re.sub(r"\[Inferior\s+\d+[^\]]*\]\s*", "", text)
    cleaned: list[str] = []
    metadata = re.compile(
        r"^(?:Breakpoint \d+|\[Inferior |\[New Thread |\[Thread |"
        r"During startup program |warning: )"
    )
    signal = re.compile(r"^(?:Program|Thread \d+.*?) received signal ")
    for line in text.splitlines(keepends=True):
        # GDB follows a signal report with the faulting frame and source line;
        # the stopped program cannot print anything after it.
        if signal.match(line.strip()):
            # GDB opens the report with a newline of its own ("\nProgram received signal").
            if cleaned and cleaned[-1].endswith("\n"):
                cleaned[-1] = cleaned[-1][:-1]
                if cleaned[-1].endswith("\r"):
                    cleaned[-1] = cleaned[-1][:-1]
            break
        if metadata.match(line.strip()):
            continue
        if line.strip() == LIMIT_MARKER:
            continue
        cleaned.append(line)
    # A leading newline is the program's own (`cout << "\n";` on its own line), so it stays.
    return "".join(cleaned)


def _execution_status(output: str, errors: str) -> tuple[str, dict[str, str] | None]:
    signal_match = re.search(
        r"(?:Program|Thread\s+\d+(?:\s+\"[^\"]*\")?)\s+received signal\s+([A-Z0-9_]+),\s*([^\r\n]+)",
        output,
    )
    if signal_match:
        error = {
            "type": signal_match.group(1),
            "message": signal_match.group(2).strip(),
        }
        return "exception", error
    exit_match = re.search(
        r"\[Inferior\s+\d+\s+\(process\s+\d+\)\s+exited with code\s+(\w+)\]",
        output,
    )
    if exit_match and exit_match.group(1).strip() not in {"0", "00"}:
        thrown = re.search(
            r"terminate called after throwing an instance of '([^']+)'"
            r"(?:\s*\n\s*what\(\):\s*([^\r\n]*))?",
            errors,
        )
        if thrown:
            return "exception", {
                "type": thrown.group(1),
                "message": (thrown.group(2) or "").strip() or "Uncaught C++ exception.",
            }
        # `assert` prints its condition to stderr, then aborts with exit code 3.
        failed = re.search(r"Assertion failed[:!]?\s*([^\r\n]*?)(?:,\s*file\s+[^,\r\n]+,\s*line\s+\d+)?\s*$", errors, re.M)
        if failed:
            condition = failed.group(1).strip()
            return "exception", {
                "type": "AssertionFailed",
                "message": f"assert({condition}) failed." if condition else "An assert failed.",
            }
        # GDB prints the exit code in octal (`exited with code 012` is 10).
        raw = exit_match.group(1).strip()
        code = int(raw, 8) if re.fullmatch(r"[0-7]+", raw) else raw
        return "exception", {
            "type": "NonZeroExit",
            "message": f"Program exited with code {code}.",
        }
    fatal = "\n".join(
        line for line in errors.splitlines() if "index cache directory" not in line
    ).strip()
    if fatal and "No such file or directory" in fatal:
        return "exception", {"type": "DebuggerError", "message": fatal[:2_000]}
    return "completed", None


def _debugger_error(line: int, errors: str) -> dict[str, str]:
    detail = next(
        (
            text.strip()
            for text in errors.splitlines()
            if text.strip()
            and "index cache directory" not in text
            and "Error in sourced command file" not in text
        ),
        "GDB stopped executing the trace commands.",
    )
    location = f" at line {line}" if line else ""
    return {
        "type": "DebuggerError",
        "message": f"The C++ tracer could not read the program state{location}: {detail}"[:2_000],
    }
