from __future__ import annotations

from sentinel.analysis.diff.parser import parse_unified_diff
from sentinel.analysis.graph.context import ContextEngine
from sentinel.core.domain.graph import NodeKind
from tests.helpers import build_shop

DIFF = """\
diff --git a/app/db.py b/app/db.py
--- a/app/db.py
+++ b/app/db.py
@@ -9,4 +9,4 @@ def find_user(name, password):
     conn = connect()
     cur = conn.cursor()
-    cur.execute("SELECT * FROM users WHERE name = ? AND password = ?", (name, password))
+    cur.execute(f"SELECT * FROM users WHERE name = '{name}' AND password = '{password}'")
     return cur.fetchone()
diff --git a/app/services.py b/app/services.py
--- a/app/services.py
+++ b/app/services.py
@@ -1,2 +1,3 @@
 from app import db
+TIMEOUT = 5

"""


def _engine(max_chars: int = 60_000) -> ContextEngine:
    sources, res = build_shop()
    return ContextEngine(res.graph, sources, res.files, max_chars=max_chars)


def test_changed_symbols_include_module_level() -> None:
    engine = _engine()
    changed = engine.changed_symbols(parse_unified_diff(DIFF))
    by_name = {c.name: c for c in changed}
    assert by_name["find_user"].changed_lines == [11]
    assert by_name["app/services.py"].kind is NodeKind.FILE


def test_context_blocks_cover_callers_callees_paths() -> None:
    bundle = _engine().build(parse_unified_diff(DIFF))
    kinds = {(b.kind, b.symbol) for b in bundle.blocks}
    assert ("changed", "find_user") in kinds
    assert ("caller", "authenticate") in kinds
    assert ("callee", "connect") in kinds
    assert any(b.kind == "endpoint" and "POST /login" in b.code for b in bundle.blocks)
    assert any(b.kind == "data" and "reads users" in b.code for b in bundle.blocks)
    changed = next(b for b in bundle.blocks if b.kind == "changed" and b.symbol == "find_user")
    assert "11 |" in changed.code  # numbered lines, so the model can cite them
    assert bundle.stats["changed_symbols"] == 2
    assert not bundle.truncated
    path = next(iter(bundle.call_paths.values()))
    assert path[0] == "POST /login"


def test_budget_truncates_low_priority_first() -> None:
    bundle = _engine(max_chars=700).build(parse_unified_diff(DIFF))
    assert bundle.truncated
    assert bundle.dropped
    assert bundle.blocks[0].kind == "changed"
    assert all(b.kind != "import" for b in bundle.blocks)


def test_context_is_redacted() -> None:
    sources, res = build_shop()
    token = "ghp_" + "Z" * 36
    sources = dict(sources)
    sources["app/db.py"] = sources["app/db.py"].replace(
        "conn = connect()\n    cur", f"conn = connect()  # {token}\n    cur", 1
    )
    engine = ContextEngine(res.graph, sources, res.files)
    bundle = engine.build(parse_unified_diff(DIFF))
    assert bundle.redactions >= 1
    assert all(token not in b.code for b in bundle.blocks)


def test_ui_subgraph_marks_changed_nodes() -> None:
    bundle = _engine().build(parse_unified_diff(DIFF))
    sub = bundle.subgraph
    changed = [n for n in sub.nodes if n.meta.get("changed") == "true"]
    assert [n.name for n in changed] == ["find_user"]
    names = {n.name for n in sub.nodes}
    assert {"authenticate", "connect", "POST /login", "users"} <= names
    assert all(n.kind is not NodeKind.FILE for n in sub.nodes)
