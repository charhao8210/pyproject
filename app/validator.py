from __future__ import annotations

import ast
from dataclasses import dataclass


MAX_SOURCE_LENGTH = 50_000

# The runtime returns restricted namespaces containing only these public members.
# Keeping validation and execution on one allowlist prevents importing a module's
# implementation helpers (or its own imported modules) through a from-import.
ALGORITHM_MODULE_MEMBERS: dict[str, frozenset[str]] = {
    "sys": frozenset({"stdin"}),
    "heapq": frozenset({
        "heapify", "heappop", "heappush", "heappushpop", "heapreplace",
        "merge", "nlargest", "nsmallest", "heapify_max", "heappop_max",
        "heappush_max", "heappushpop_max", "heapreplace_max",
    }),
    "bisect": frozenset({
        "bisect", "bisect_left", "bisect_right", "insort", "insort_left", "insort_right",
    }),
    "collections": frozenset({"deque", "defaultdict", "Counter"}),
    "math": frozenset({
        "acos", "acosh", "asin", "asinh", "atan", "atan2", "atanh", "cbrt",
        "ceil", "comb", "copysign", "cos", "cosh", "degrees", "dist", "e",
        "erf", "erfc", "exp", "exp2", "expm1", "fabs", "factorial", "floor",
        "fmod", "frexp", "fsum", "gamma", "gcd", "hypot", "inf", "isclose",
        "isfinite", "isinf", "isnan", "isqrt", "lcm", "ldexp", "lgamma",
        "log", "log10", "log1p", "log2", "modf", "nan", "nextafter", "perm",
        "pi", "pow", "prod", "radians", "remainder", "sin", "sinh", "sqrt",
        "sumprod", "tan", "tanh", "tau", "trunc", "ulp",
    }),
}
SAFE_IMPORT_MESSAGE = "Available algorithm modules: sys, heapq, bisect, collections and math."


@dataclass(frozen=True)
class ValidationIssue:
    message: str
    line: int | None = None
    column: int | None = None

    def as_dict(self) -> dict[str, str | int | None]:
        return {
            "message": self.message,
            "line": self.line,
            "column": self.column,
        }


class SourceValidationError(ValueError):
    def __init__(self, issues: list[ValidationIssue]):
        super().__init__(issues[0].message if issues else "Invalid source code")
        self.issues = issues


class _SafetyVisitor(ast.NodeVisitor):
    blocked_calls = {"open", "eval", "exec", "compile", "__import__"}

    def __init__(self) -> None:
        self.issues: list[ValidationIssue] = []

    def _reject(self, node: ast.AST, message: str) -> None:
        self.issues.append(
            ValidationIssue(
                message=message,
                line=getattr(node, "lineno", None),
                column=(getattr(node, "col_offset", 0) + 1)
                if hasattr(node, "col_offset")
                else None,
            )
        )

    def visit_Import(self, node: ast.Import) -> None:
        if any(alias.name not in ALGORITHM_MODULE_MEMBERS for alias in node.names):
            self._reject(node, SAFE_IMPORT_MESSAGE)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        allowed_members = ALGORITHM_MODULE_MEMBERS.get(node.module or "", frozenset())
        allowed = node.level == 0 and bool(allowed_members) and all(alias.name in allowed_members for alias in node.names)
        if not allowed:
            self._reject(node, "Only listed public members of algorithm modules may be imported. " + SAFE_IMPORT_MESSAGE)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._reject(node, "Async code is not supported in the MVP.")

    def visit_Await(self, node: ast.Await) -> None:
        self._reject(node, "Async code is not supported in the MVP.")

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._reject(node, "Async code is not supported in the MVP.")

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self._reject(node, "Async code is not supported in the MVP.")

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in self.blocked_calls:
            self._reject(node, f"Calling {node.func.id}() is not allowed.")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("__"):
            self._reject(node, "Dunder attribute access is not allowed.")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == "__builtins__":
            self._reject(node, "Access to __builtins__ is not allowed.")


def validate_source(source: str) -> ast.Module:
    if len(source) > MAX_SOURCE_LENGTH:
        raise SourceValidationError(
            [ValidationIssue(f"Source code must be at most {MAX_SOURCE_LENGTH} characters.")]
        )

    try:
        tree = ast.parse(source, filename="<user_code>", mode="exec")
    except SyntaxError as error:
        raise SourceValidationError(
            [
                ValidationIssue(
                    message=error.msg,
                    line=error.lineno,
                    column=error.offset,
                )
            ]
        ) from error

    visitor = _SafetyVisitor()
    visitor.visit(tree)
    if visitor.issues:
        raise SourceValidationError(visitor.issues)
    return tree
