from __future__ import annotations

import ast
from dataclasses import dataclass


MAX_SOURCE_LENGTH = 50_000


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
        if any(alias.name != "sys" for alias in node.names):
            self._reject(node, "Only the sys module is available for standard input.")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        allowed = node.module == "sys" and all(
            alias.name == "stdin" for alias in node.names
        )
        if not allowed:
            self._reject(node, "Only 'from sys import stdin' is allowed.")

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
