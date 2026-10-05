from __future__ import annotations

import builtins
import bisect as _algorithm_bisect
import collections as _algorithm_collections
import heapq as _algorithm_heapq
import io
import math as _algorithm_math
import sys
from types import FrameType, SimpleNamespace
from typing import Any, Callable

from .serializer import SerializationContext, serialize_locals, serialize_value
from .validator import ALGORITHM_MODULE_MEMBERS, SAFE_IMPORT_MESSAGE


USER_FILENAME = "<user_code>"
DEFAULT_MAX_STEPS = 5_000
MAX_STDOUT_LENGTH = 100_000
# Nested user calls allowed before the trace reports RecursionError, matching Python's default.
MAX_RECURSION_DEPTH = 1_000
RECURSION_MESSAGE = f"maximum recursion depth exceeded ({MAX_RECURSION_DEPTH} nested calls)"
# Frames kept in each step's `stack`: the outermost one plus the innermost rest.
MAX_RECORDED_FRAMES = 40


class StepLimitExceeded(BaseException):
    pass


class CappedOutput(io.TextIOBase):
    def __init__(self, limit: int = MAX_STDOUT_LENGTH) -> None:
        self.limit = limit
        self._parts: list[str] = []
        self._length = 0
        self.truncated = False

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        if not isinstance(text, str):
            raise TypeError("write() argument must be str")
        remaining = self.limit - self._length
        if remaining > 0:
            chunk = text[:remaining]
            self._parts.append(chunk)
            self._length += len(chunk)
        if len(text) > remaining:
            self.truncated = True
        return len(text)

    def flush(self) -> None:
        return None

    def getvalue(self) -> str:
        suffix = "\n… stdout truncated …" if self.truncated else ""
        return "".join(self._parts) + suffix


SAFE_BUILTIN_NAMES = {
    "abs",
    "all",
    "any",
    "bool",
    "chr",
    "dict",
    "divmod",
    "enumerate",
    "filter",
    "float",
    "format",
    "frozenset",
    "int",
    "isinstance",
    "issubclass",
    "iter",
    "len",
    "list",
    "map",
    "max",
    "min",
    "next",
    "object",
    "ord",
    "pow",
    "print",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "slice",
    "sorted",
    "str",
    "sum",
    "super",
    "tuple",
    "type",
    "zip",
    "BaseException",
    "Exception",
    "ArithmeticError",
    "AssertionError",
    "AttributeError",
    "EOFError",
    "IndexError",
    "KeyError",
    "LookupError",
    "NameError",
    "NotImplementedError",
    "OverflowError",
    "RuntimeError",
    "StopIteration",
    "TypeError",
    "ValueError",
    "ZeroDivisionError",
    "__build_class__",
}


def _safe_builtins(
    input_stream: io.TextIOBase,
    output: CappedOutput,
    safe_sys: SimpleNamespace,
) -> dict[str, Any]:
    allowed = {name: getattr(builtins, name) for name in SAFE_BUILTIN_NAMES}
    algorithm_modules = {
        "heapq": _algorithm_heapq,
        "bisect": _algorithm_bisect,
        "collections": _algorithm_collections,
        "math": _algorithm_math,
    }
    safe_modules = {
        name: SimpleNamespace(**{
            member: getattr(module, member)
            for member in ALGORITHM_MODULE_MEMBERS[name]
            if hasattr(module, member)
        })
        for name, module in algorithm_modules.items()
    }
    safe_modules["sys"] = safe_sys

    def safe_input(prompt: object = "") -> str:
        if prompt:
            output.write(str(prompt))
        line = input_stream.readline()
        if line == "":
            raise EOFError("EOF when reading a line")
        return line.rstrip("\r\n")

    def safe_import(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> SimpleNamespace:
        del globals, locals
        if level != 0 or name not in safe_modules:
            raise ImportError(SAFE_IMPORT_MESSAGE)
        members = ALGORITHM_MODULE_MEMBERS[name]
        if any(member not in members for member in (fromlist or ())):
            raise ImportError("Only listed public members of algorithm modules may be imported.")
        return safe_modules[name]

    allowed["input"] = safe_input
    allowed["__import__"] = safe_import
    return allowed


class ExecutionTracer:
    def __init__(
        self,
        output: CappedOutput,
        max_steps: int,
        on_step: Callable[[dict[str, Any]], None] | None = None,
        capture_items: int = 50,
        capture_depth: int = 4,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self.output = output
        self.max_steps = max_steps
        self.steps: list[dict[str, Any]] = []
        self.stopped = False
        self.on_step = on_step
        self.capture_items = capture_items
        self.capture_depth = capture_depth

    def trace(self, frame: FrameType, event: str, arg: Any) -> Callable[..., Any] | None:
        if frame.f_code.co_filename != USER_FILENAME:
            return self.trace
        if event not in {"call", "line", "return", "exception"}:
            return self.trace

        if event == "call" and frame.f_code.co_name == "<module>":
            return self.trace

        if len(self.steps) >= self.max_steps - 1:
            self._append_stopped_step(frame)
            self.stopped = True
            raise StepLimitExceeded

        if event == "call" and self._call_depth(frame) > MAX_RECURSION_DEPTH:
            # Raising from the trace function stops tracing, so the error unwinds the stack
            # without recording another step per frame. The step is shown at the caller's line,
            # which is the recursive call that went too deep.
            caller = frame.f_back if frame.f_back and frame.f_back.f_code.co_filename == USER_FILENAME else frame
            error = RecursionError(RECURSION_MESSAGE)
            self._record(self._snapshot(caller, "exception", (RecursionError, error, None)))
            raise error

        self._record(self._snapshot(frame, event, arg))
        return self.trace

    def _record(self, snapshot: dict[str, Any]) -> None:
        self.steps.append(snapshot)
        if self.on_step is not None:
            self.on_step(snapshot)

    @staticmethod
    def _call_depth(frame: FrameType) -> int:
        """Count nested user function calls, not counting the module frame."""
        depth = 0
        current: FrameType | None = frame
        while current is not None:
            if current.f_code.co_filename == USER_FILENAME and current.f_code.co_name != "<module>":
                depth += 1
            current = current.f_back
        return depth

    def _snapshot(self, frame: FrameType, event: str, arg: Any) -> dict[str, Any]:
        context = SerializationContext(max_items=self.capture_items, max_depth=self.capture_depth)
        snapshot: dict[str, Any] = {
            "step": len(self.steps),
            "event": event,
            "filename": USER_FILENAME,
            "function": frame.f_code.co_name,
            "line": frame.f_lineno,
            "locals": serialize_locals(frame.f_locals, context=context),
            "globals": (
                {}
                if frame.f_code.co_name == "<module>"
                else serialize_locals(frame.f_globals, context=context)
            ),
            **self._stack(frame),
            "stdout": self.output.getvalue(),
        }
        if event == "return":
            snapshot["return_value"] = serialize_value(
                arg, context=SerializationContext(max_items=self.capture_items, max_depth=self.capture_depth)
            )
        elif event == "exception":
            exception_type, exception_value, _ = arg
            snapshot["exception"] = _exception_info(exception_type, exception_value)
        return snapshot

    def _stack(self, frame: FrameType) -> dict[str, Any]:
        """Return `stack` (outermost frame plus the innermost ones) and the full `depth`.

        Deep recursion would otherwise copy every frame into every step, which makes the trace
        quadratic in size: 1,000 nested calls meant about a million frame records.
        """
        frames: list[dict[str, str | int]] = []
        current: FrameType | None = frame
        while current is not None:
            if current.f_code.co_filename == USER_FILENAME:
                frames.append(
                    {
                        "function": current.f_code.co_name,
                        "line": current.f_lineno,
                    }
                )
            current = current.f_back
        frames.reverse()
        depth = len(frames)
        if depth > MAX_RECORDED_FRAMES:
            frames = [frames[0], *frames[-(MAX_RECORDED_FRAMES - 1):]]
        return {"stack": frames, "depth": depth}

    def _append_stopped_step(self, frame: FrameType) -> None:
        context = SerializationContext(max_items=self.capture_items, max_depth=self.capture_depth)
        snapshot = {
                "step": len(self.steps),
                "event": "stopped",
                "filename": USER_FILENAME,
                "function": frame.f_code.co_name,
                "line": frame.f_lineno,
                "locals": serialize_locals(frame.f_locals, context=context),
                "globals": (
                    {}
                    if frame.f_code.co_name == "<module>"
                    else serialize_locals(frame.f_globals, context=context)
                ),
                **self._stack(frame),
                "stdout": self.output.getvalue(),
                "exception": {
                    "type": "StepLimitExceeded",
                    "message": "Execution stopped: step limit exceeded",
                },
            }
        self.steps.append(snapshot)
        if self.on_step is not None:
            self.on_step(snapshot)


def _exception_info(exception_type: type[BaseException], value: BaseException) -> dict[str, str]:
    try:
        message = str(value)
    except BaseException:
        message = "The exception message could not be rendered."
    return {"type": exception_type.__name__, "message": message}


def trace_code(
    source: str,
    stdin_text: str = "",
    max_steps: int = DEFAULT_MAX_STEPS,
    on_step: Callable[[dict[str, Any]], None] | None = None,
    capture_items: int = 50,
    capture_depth: int = 4,
) -> dict[str, Any]:
    output = CappedOutput()
    input_buffer = io.BytesIO(stdin_text.encode("utf-8"))
    input_stream = io.TextIOWrapper(input_buffer, encoding="utf-8", newline=None)
    safe_sys = SimpleNamespace(stdin=input_stream)
    tracer = ExecutionTracer(output, max_steps, on_step=on_step, capture_items=capture_items, capture_depth=capture_depth)
    namespace: dict[str, Any] = {
        "__name__": "__main__",
        "__builtins__": _safe_builtins(input_stream, output, safe_sys),
    }
    compiled = compile(source, USER_FILENAME, "exec")
    old_stdout = sys.stdout
    old_trace = sys.gettrace()
    status = "completed"
    error: dict[str, str] | None = None

    try:
        sys.stdout = output
        sys.settrace(tracer.trace)
        exec(compiled, namespace, namespace)
    except StepLimitExceeded:
        status = "step_limit"
        error = {
            "type": "StepLimitExceeded",
            "message": "Execution stopped: step limit exceeded",
        }
    except BaseException as exception:
        status = "exception"
        error = _exception_info(type(exception), exception)
        _ensure_unhandled_exception_is_last(tracer.steps, error, output.getvalue())
    finally:
        sys.settrace(old_trace)
        sys.stdout = old_stdout

    return {
        "source": source,
        "stdin": stdin_text,
        "steps": tracer.steps,
        "status": status,
        "error": error,
    }


def _ensure_unhandled_exception_is_last(
    steps: list[dict[str, Any]],
    error: dict[str, str],
    stdout: str,
) -> None:
    matching_step = next(
        (
            step
            for step in reversed(steps)
            if step.get("event") == "exception"
            and step.get("exception", {}).get("type") == error["type"]
            and step.get("exception", {}).get("message") == error["message"]
        ),
        None,
    )
    if matching_step is None:
        # The error was raised where no exception event was recorded (for example inside a
        # builtin), so mark the last executed line as the place it failed.
        if steps:
            final_step = {key: value for key, value in steps[-1].items() if key != "return_value"}
            final_step["step"] = len(steps)
            final_step["event"] = "exception"
            final_step["exception"] = error
            final_step["stdout"] = stdout
            steps.append(final_step)
        return
    if steps and steps[-1] is matching_step:
        return
    final_step = dict(matching_step)
    final_step["step"] = len(steps)
    final_step["stdout"] = stdout
    steps.append(final_step)
