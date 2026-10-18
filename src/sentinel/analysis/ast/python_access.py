"""Extract global-variable access without confusing local names with dependencies.

The Python adapter calls this after parsing. The standard-library symbol table handles
parameters, assignments, ``global`` and closures; no repository code is imported.
Comprehensions and lambdas are deliberately omitted until their own scopes are modeled.
"""

from __future__ import annotations

import ast
import symtable

from sentinel.core.domain.code import VariableAccess

MODULE = "<module>"


class _AccessVisitor(ast.NodeVisitor):
    def __init__(self, table: symtable.SymbolTable, owner: str = MODULE) -> None:
        self.table = table
        self.owner = owner
        self.accesses: list[VariableAccess] = []

    def _global(self, name: str) -> bool:
        try:
            return self.table.lookup(name).is_global()
        except KeyError:
            return False

    def _record(self, name: str, node: ast.expr | ast.stmt, operation: str) -> None:
        self.accesses.append(
            VariableAccess(symbol=self.owner, name=name, line=node.lineno, operation=operation)
        )

    def visit_Name(self, node: ast.Name) -> None:
        if self._global(node.id):
            self._record(node.id, node, "read" if isinstance(node.ctx, ast.Load) else "write")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.value, ast.Name) and self._global(node.value.id):
            name = f"{node.value.id}.{node.attr}"
            self._record(name, node, "read" if isinstance(node.ctx, ast.Load) else "write")
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.target, ast.Name) and self._global(node.target.id):
            self._record(node.target.id, node, "read")
        self.generic_visit(node)

    def _definition(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                self.visit(base)
        else:
            for default in [*node.args.defaults, *node.args.kw_defaults]:
                if default is not None:
                    self.visit(default)
        child = next(
            (
                table
                for table in self.table.get_children()
                if table.get_name() == node.name and table.get_lineno() == node.lineno
            ),
            None,
        )
        if child is None:
            return
        owner = node.name if self.owner == MODULE else f"{self.owner}.{node.name}"
        visitor = _AccessVisitor(child, owner)
        for statement in node.body:
            visitor.visit(statement)
        self.accesses.extend(visitor.accesses)

    visit_FunctionDef = _definition
    visit_AsyncFunctionDef = _definition
    visit_ClassDef = _definition

    def visit_Lambda(self, node: ast.Lambda) -> None:
        """Leave anonymous scopes unmodeled rather than inventing global relationships."""

    def _comprehension(
        self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp
    ) -> None:
        # Only the outer iterable executes in the enclosing scope.
        self.visit(node.generators[0].iter)

    visit_ListComp = _comprehension
    visit_SetComp = _comprehension
    visit_DictComp = _comprehension
    visit_GeneratorExp = _comprehension


def global_accesses(tree: ast.Module, path: str, source: str) -> list[VariableAccess]:
    """Return observed global reads/writes, excluding annotations and anonymous scopes."""
    visitor = _AccessVisitor(symtable.symtable(source, path, "exec"))
    visitor.visit(tree)
    return visitor.accesses
