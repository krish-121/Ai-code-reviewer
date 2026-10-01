"""Python analyzer: symbols, imports, calls, endpoints and database operations."""

from __future__ import annotations

from sentinel.analysis.ast.python_analyzer import (
    PythonAnalyzer,
    is_python_test_file,
    module_name_for,
)
from sentinel.analysis.ast.python_sql import classify_sql, sql_tables
from sentinel.core.domain.code import SymbolKind

SRC = """\
import os
import app.db as database
from .models import User as U, Order
from . import utils

API_KEY = os.environ.get("KEY")


class Repo(Base, mixins.Audit):
    @staticmethod
    def build():
        return Repo()

    async def fetch(self, ids):
        rows = []
        for i in ids:
            rows.append(await self.cursor.execute("SELECT * FROM users WHERE id = %s", (i,)))
        return [self.session.query(U).filter_by(id=r) for r in rows]


@app.route("/items", methods=["GET", "POST"])
def items():
    def inner():
        return helper()
    return inner()


@router.delete("/items/{item_id}")
async def delete_item(item_id: int, *args, force=False, **kw):
    db.session.delete(item_id)
    db.session.commit()


if __name__ == "__main__":
    main()
"""


def analyze(src: str = SRC, path: str = "pkg/app/repo.py"):
    return PythonAnalyzer().analyze(path, src)


def test_symbols_and_spans() -> None:
    fs = analyze()
    by_qn = {s.qualified_name: s for s in fs.symbols}
    assert by_qn["<module>"].kind is SymbolKind.MODULE
    assert by_qn["Repo"].kind is SymbolKind.CLASS
    assert by_qn["Repo"].bases == ["Base", "mixins.Audit"]
    assert by_qn["Repo.build"].kind is SymbolKind.METHOD
    assert by_qn["Repo.build"].decorators == ["staticmethod"]
    assert by_qn["Repo.fetch"].is_async
    assert by_qn["Repo.fetch"].parent == "Repo"
    assert by_qn["items.inner"].kind is SymbolKind.FUNCTION
    assert by_qn["delete_item"].params == ["item_id", "force", "*args", "**kw"]
    assert by_qn["API_KEY"].kind is SymbolKind.VARIABLE
    main = by_qn["__main__"]
    assert (main.line_start, main.line_end) == (34, 35)
    # decorator lines are part of the symbol span
    assert by_qn["items"].line_start == 21


def test_imports() -> None:
    fs = analyze()
    imps = {(i.module, i.level): i for i in fs.imports}
    assert imps[("app.db", 0)].aliases == {"database": "app.db"}
    assert imps[("models", 1)].aliases == {"U": "User", "Order": "Order"}
    assert imps[("", 1)].names == ["utils"]
    assert imps[("os", 0)].aliases == {"os": "os"}


def test_calls_loops_and_await() -> None:
    fs = analyze()
    calls = {(c.caller, c.callee): c for c in fs.calls}
    ex = calls[("Repo.fetch", "self.cursor.execute")]
    assert ex.in_loop and ex.awaited
    assert calls[("Repo.fetch", "self.session.query.filter_by")].in_loop  # comprehension
    assert calls[("items.inner", "helper")].caller == "items.inner"
    assert ("__main__", "main") in calls
    assert not calls[("<module>", "os.environ.get")].in_loop


def test_endpoints() -> None:
    fs = analyze()
    eps = {(e.method, e.route): e.handler for e in fs.endpoints}
    assert eps == {
        ("GET", "/items"): "items",
        ("POST", "/items"): "items",
        ("DELETE", "/items/{item_id}"): "delete_item",
    }


def test_db_operations() -> None:
    fs = analyze()
    ops = [(o.function, o.operation, o.in_loop) for o in fs.db_operations]
    assert ("Repo.fetch", "read", True) in ops
    assert ("delete_item", "write", False) in ops
    detail = next(o.detail for o in fs.db_operations if "execute" in o.detail)
    assert "[users]" in detail


def test_syntax_error_is_reported() -> None:
    fs = analyze("def broken(:\n    pass\n")
    assert fs.parse_error is not None and "SyntaxError" in fs.parse_error
    assert fs.symbols == []


def test_test_file_detection_and_test_symbols() -> None:
    fs = PythonAnalyzer().analyze(
        "tests/test_repo.py", "class TestRepo:\n    def test_a(self):\n        run()\n"
    )
    assert fs.is_test_file
    kinds = {s.qualified_name: s.kind for s in fs.symbols}
    assert kinds["TestRepo.test_a"] is SymbolKind.TEST
    assert is_python_test_file("pkg/foo_test.py")
    assert not is_python_test_file("pkg/testing_utils.py")


def test_module_names_and_sql_helpers() -> None:
    assert module_name_for("src/pkg/__init__.py") == "pkg"
    assert module_name_for("pkg/a/b.py") == "pkg.a.b"
    assert classify_sql("  select 1") == "read"
    assert classify_sql("WITH x AS (select 1) select * from x") == "read"
    assert classify_sql("DELETE FROM t") == "write"
    assert classify_sql(None) == "unknown"
    assert classify_sql("vacuum") == "unknown"
    assert sql_tables("SELECT * FROM a JOIN public.B ON 1 INSERT INTO c") == ["a", "b", "c"]


def test_symbol_at_prefers_innermost() -> None:
    fs = analyze()
    sym = fs.symbol_at(24)
    assert sym is not None and sym.qualified_name == "items.inner"
    assert fs.symbol_at(1) is None
