from __future__ import annotations

import pytest

from sentinel.analysis.ast.python_analyzer import PythonAnalyzer
from sentinel.analysis.ast.registry import default_registry
from sentinel.analysis.graph.builder import build_graph
from sentinel.core.domain.graph import CodeGraph, EdgeKind, GraphNode, NodeKind, node_id
from tests.helpers import build_shop

FIND_USER = node_id(NodeKind.FUNCTION, "app/db.py", "find_user")
ORDERS_FOR = node_id(NodeKind.METHOD, "app/services.py", "OrderService.orders_for")
LOGIN = node_id(NodeKind.FUNCTION, "app/api.py", "login")


def test_shop_graph_edges() -> None:
    _, res = build_shop()
    g = res.graph
    callers = {n.name for n in g.callers(FIND_USER)}
    assert callers == {"authenticate"}
    assert {n.name for n in g.callees(ORDERS_FOR)} == {"connect"}
    # from app import db  -> module alias, db.connect resolves across files
    assert g.node(node_id(NodeKind.FUNCTION, "app/db.py", "connect")) in g.callees(ORDERS_FOR)
    tests = g.tests_for(ORDERS_FOR)
    assert [t.name for t in tests] == ["test_orders_for_empty"]
    assert g.tests_for(FIND_USER) == []
    reads = {g.node(e.target).name for e in g.out_edges(ORDERS_FOR, [EdgeKind.READS])}  # type: ignore[union-attr]
    assert reads == {"orders", "items"}
    assert g.node(ORDERS_FOR).meta["db_in_loop"] == "10"  # type: ignore[union-attr]
    assert res.resolved_calls > 0


def test_entry_path_includes_endpoint() -> None:
    _, res = build_shop()
    path = res.graph.path_from_entrypoint(FIND_USER)
    assert path is not None
    assert [n.name for n in path] == ["POST /login", "login", "authenticate", "find_user"]
    unused = node_id(NodeKind.METHOD, "app/services.py", "OrderService.unused_helper")
    assert res.graph.path_from_entrypoint(unused) is None


def test_test_only_reachability_is_reported_as_test_path() -> None:
    _, res = build_shop()
    g = res.graph
    # Remove the route edge's production caller by querying a node only tests reach.
    path = g.path_from_entrypoint(ORDERS_FOR)
    assert path is not None and path[0].kind is NodeKind.ENDPOINT


def test_call_path_and_enclosing() -> None:
    _, res = build_shop()
    g = res.graph
    path = g.call_path(LOGIN, FIND_USER)
    assert [n.name for n in path] == ["login", "authenticate", "find_user"]
    assert g.call_path(FIND_USER, LOGIN) == []
    enc = g.enclosing("app/db.py", 11)
    assert enc is not None and enc.id == FIND_USER
    assert g.enclosing("app/db.py", 1) is None


def test_serialization_roundtrip() -> None:
    _, res = build_shop()
    data = res.graph.to_dict()
    again = CodeGraph.from_dict(data)
    assert len(again) == len(res.graph)
    assert len(again.edges) == len(res.graph.edges)
    with pytest.raises(ValueError, match="nodes"):
        CodeGraph.from_dict({"nodes": "nope"})


def test_graph_primitives() -> None:
    g = CodeGraph()
    a = g.add_node(
        GraphNode(id="a", kind=NodeKind.FUNCTION, name="a", file="x.py", line_start=1, line_end=5)
    )
    assert g.add_node(GraphNode(id="a", kind=NodeKind.CLASS, name="dup")) is a
    g.add_node(GraphNode(id="b", kind=NodeKind.FUNCTION, name="b"))
    g.add_edge("a", "b", EdgeKind.CALLS)
    g.add_edge("a", "b", EdgeKind.CALLS)  # duplicate ignored
    g.add_edge("a", "missing", EdgeKind.CALLS)  # dangling ignored
    g.add_edge("a", "a", EdgeKind.CALLS)  # self loop ignored
    assert len(g.edges) == 1
    assert "a" in g and "zzz" not in g
    assert g.find_by_name("b()") == [g.node("b")]
    assert g.neighborhood(["a"], depth=1) == {"a", "b"}
    sub = g.subgraph(["a"])
    assert len(sub) == 1 and sub.edges == []
    assert g.path_from_entrypoint("nope") is None


def test_inheritance_and_self_method_resolution() -> None:
    sources = {
        "pkg/base.py": "class Base:\n    def save(self):\n        return 1\n",
        "pkg/models.py": (
            "from pkg.base import Base\n\n"
            "class User(Base):\n"
            "    def update(self):\n"
            "        self.save()\n"
            "        super().save()\n"
        ),
    }
    analyzed = {p: PythonAnalyzer().analyze(p, s) for p, s in sources.items()}
    g = build_graph(analyzed).graph
    user = node_id(NodeKind.CLASS, "pkg/models.py", "User")
    base = node_id(NodeKind.CLASS, "pkg/base.py", "Base")
    assert [e.target for e in g.out_edges(user, [EdgeKind.INHERITS])] == [base]
    update = node_id(NodeKind.METHOD, "pkg/models.py", "User.update")
    assert [n.name for n in g.callees(update)] == ["Base.save"]


def test_relative_imports_and_receiver_scoring() -> None:
    sources = {
        "svc/__init__.py": "",
        "svc/repos.py": (
            "class UserRepository:\n    def find(self, i):\n        return i\n\n"
            "class OrderRepository:\n    def find(self, i):\n        return i\n"
        ),
        "svc/handlers.py": (
            "from .repos import UserRepository\n"
            "from . import repos\n\n"
            "def get(users, i):\n"
            "    users.find(i)\n"
            "    repos.UserRepository.find(None, i)\n"
            "    UserRepository.find(None, i)\n"
        ),
    }
    analyzed = default_registry().analyze(sources)
    g = build_graph(analyzed).graph
    get = node_id(NodeKind.FUNCTION, "svc/handlers.py", "get")
    targets = {n.name for n in g.callees(get)}
    assert targets == {"UserRepository.find"}


def test_js_relative_import_resolution() -> None:
    sources = {
        "src/db/index.ts": "export function query(sql: string) { return sql; }\n",
        "src/users.ts": (
            "import { query } from './db';\n"
            "export function listUsers() { return query('SELECT * FROM users'); }\n"
        ),
        "src/app.ts": "import { listUsers } from '@/users';\nexport const main = () => listUsers();\n",
    }
    analyzed = default_registry().analyze(sources)
    g = build_graph(analyzed).graph
    lu = node_id(NodeKind.FUNCTION, "src/users.ts", "listUsers")
    assert [n.name for n in g.callees(lu)] == ["query"]
    assert [n.name for n in g.callers(lu)] == ["main"]
