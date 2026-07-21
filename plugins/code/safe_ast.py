"""
AST-based guard for user-submitted Python (code_interpreter).
Blocks imports/calls that enable RCE or exfiltration beyond the subprocess script.
"""
from __future__ import annotations

import ast
from typing import Optional

_FORBIDDEN_NAMES = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "open",
        "input",
        "breakpoint",
        "exit",
        "quit",
        "help",
        "globals",
        "locals",
        "vars",
        "setattr",
        "delattr",
    }
)

_FORBIDDEN_MODULES = frozenset(
    {
        "os",
        "subprocess",
        "sys",
        "socket",
        "shutil",
        "pathlib",
        "requests",
        "httpx",
        "urllib",
        "multiprocessing",
        "ctypes",
        "importlib",
        "pty",
        "ssl",
        "pickle",
        "shelve",
        "sqlite3",
        "tempfile",
    }
)


def assert_code_ast_safe(source: str) -> None:
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        raise ValueError(f"Syntax error: {exc}") from exc
    v = _SafetyVisitor()
    v.visit(tree)
    if v.error:
        raise ValueError(v.error)


class _SafetyVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.error: Optional[str] = None

    def _fail(self, msg: str) -> None:
        if self.error is None:
            self.error = msg

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            base = alias.name.split(".")[0]
            if base in _FORBIDDEN_MODULES:
                self._fail(f"禁止的 import: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            base = node.module.split(".")[0]
            if base in _FORBIDDEN_MODULES:
                self._fail(f"禁止的 import: {node.module}")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and node.id in _FORBIDDEN_NAMES:
            self._fail(f"禁止使用名称: {node.id}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("__") and node.attr.endswith("__"):
            self._fail("禁止访问双下划线属性")
        self.generic_visit(node)
