from __future__ import annotations

import ast
from dataclasses import dataclass


MAX_SOURCE_LENGTH = 50_000

# Modules a program may import and the members it gets (tracer._safe_builtins hands out only
# these, so a module's own imports and helpers stay out of reach).
MODULE_MEMBERS: dict[str, frozenset[str]] = {
    "sys": frozenset({"stdin", "exit", "setrecursionlimit"}),
    "heapq": frozenset({
        "heapify", "heappop", "heappush", "heappushpop", "heapreplace", "merge", "nlargest", "nsmallest",
    }),
    "bisect": frozenset({"bisect", "bisect_left", "bisect_right", "insort", "insort_left", "insort_right"}),
    "collections": frozenset({"deque", "defaultdict", "Counter"}),
    "math": frozenset({
        "acos", "asin", "atan", "atan2", "ceil", "comb", "cos", "dist", "e", "exp", "factorial",
        "floor", "fsum", "gcd", "hypot", "inf", "isqrt", "lcm", "log", "log10", "log2", "perm",
        "pi", "pow", "prod", "sin", "sqrt", "tan", "trunc",
    }),
}
SAFE_IMPORT_MESSAGE = "Only these modules can be imported: sys, collections (deque, defaultdict, Counter), heapq, bisect, math."


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
        if any(alias.name not in MODULE_MEMBERS for alias in node.names):
            self._reject(node, SAFE_IMPORT_MESSAGE)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        members = MODULE_MEMBERS.get(node.module or "", frozenset())
        if node.level or not all(alias.name in members for alias in node.names):
            self._reject(node, SAFE_IMPORT_MESSAGE)

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
