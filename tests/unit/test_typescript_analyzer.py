from __future__ import annotations

import shutil

import pytest

from sentinel.analysis.ast.registry import LanguageRegistry, default_registry
from sentinel.analysis.ast.typescript_analyzer import TypeScriptAnalyzer, find_typescript_module
from sentinel.analysis.ast.typescript_fallback import FALLBACK_NOTE, regex_extract
from sentinel.core.domain.code import SymbolKind
from sentinel.infrastructure.storage.cache import MemoryCache

HAS_TS = shutil.which("node") is not None and find_typescript_module() is not None

SERVICE = """\
import express from "express";
import { findUser as fu, db } from "./db";
import * as audit from "../audit";
const { hash } = require("./crypto");

export class UserService extends BaseService implements IRepo {
  constructor(private repo: Repo) { super(); }
  async getUser(id: string): Promise<User> {
    const u = await this.repo.find(id);
    for (const o of orders) {
      await db.query(`SELECT * FROM orders WHERE id = ${o.id}`);
    }
    items.forEach((i) => db.query("SELECT * FROM items"));
    audit.log(id);
    return fu(u);
  }
  handle = async (x: number) => hash(x);
}

export const helper = (a: number, b = 2) => a + b;
function internal() { return helper(1); }
const app = express();
app.post("/login", async (req, res) => { res.json(await login(req.body)); });
app.get("/users/:id", getUserHandler);
module.exports = { internal };
"""


@pytest.mark.node
@pytest.mark.skipif(not HAS_TS, reason="node + typescript not available")
def test_compiler_extractor_structure() -> None:
    fs = TypeScriptAnalyzer().analyze("src/service.ts", SERVICE)
    assert fs.parse_error is None
    by_qn = {s.qualified_name: s for s in fs.symbols}
    assert by_qn["UserService"].bases == ["BaseService", "IRepo"]
    assert by_qn["UserService"].exported
    assert by_qn["UserService.getUser"].kind is SymbolKind.METHOD
    assert by_qn["UserService.getUser"].params == ["id"]
    assert by_qn["UserService.handle"].is_async
    assert by_qn["helper"].exported
    assert by_qn["internal"].exported  # via module.exports
    assert by_qn["POST /login"].kind is SymbolKind.FUNCTION

    imps = {i.module: i for i in fs.imports}
    assert imps["./db"].aliases == {"fu": "findUser", "db": "db"}
    assert imps["../audit"].aliases == {"audit": "*"}
    assert imps["./crypto"].names == ["hash"]

    calls = {(c.caller, c.callee): c for c in fs.calls}
    loop_call = next(c for c in fs.calls if c.callee == "db.query" and c.line == 11)
    assert loop_call.in_loop and loop_call.awaited
    assert calls[("UserService.getUser", "this.repo.find")].awaited
    forEach_q = next(c for c in fs.calls if c.callee == "db.query" and c.line == 13)
    assert forEach_q.in_loop  # callback of forEach counts as a loop body
    assert ("POST /login", "login") in calls

    eps = {(e.method, e.route): e.handler for e in fs.endpoints}
    assert eps == {("POST", "/login"): "POST /login", ("GET", "/users/:id"): "getUserHandler"}
    tables = [o.detail for o in fs.db_operations if o.in_loop]
    assert any("[orders]" in t for t in tables) and any("[items]" in t for t in tables)


@pytest.mark.node
@pytest.mark.skipif(not HAS_TS, reason="node + typescript not available")
def test_compiler_extractor_tests_and_next_routes() -> None:
    a = TypeScriptAnalyzer()
    t = a.analyze(
        "src/__tests__/svc.test.ts",
        "describe('UserService', () => { it('gets a user', async () => {"
        " expect(await getUser('1')).toBe(1); }); });",
    )
    assert t.is_test_file
    (test,) = [s for s in t.symbols if s.kind is SymbolKind.TEST]
    assert test.name == "UserService > gets a user"
    assert any(c.caller == test.qualified_name and c.callee == "getUser" for c in t.calls)

    route = a.analyze(
        "app/api/users/route.ts",
        "export async function GET(req: Request) { return Response.json(await list()); }",
    )
    assert [(e.method, e.route) for e in route.endpoints] == [("GET", "/api/users")]


@pytest.mark.node
@pytest.mark.skipif(not HAS_TS, reason="node + typescript not available")
def test_compiler_extractor_reports_parse_errors() -> None:
    fs = TypeScriptAnalyzer().analyze("bad.ts", "function (")
    assert fs.parse_error is not None


def test_regex_fallback() -> None:
    fs = regex_extract("src/a.ts", SERVICE)
    assert fs.parse_error == FALLBACK_NOTE
    names = {s.qualified_name for s in fs.symbols}
    assert {"UserService", "UserService.getUser", "helper", "internal"} <= names
    assert any(i.module == "./db" for i in fs.imports)
    assert any(i.module == "./crypto" for i in fs.imports)
    assert any(c.callee == "helper" and c.caller == "internal" for c in fs.calls)
    js = regex_extract("lib/x.test.js", "function a(x, y = 1) {\n  return b(x);\n}\n")
    assert js.is_test_file
    assert js.symbols[1].params == ["x", "y"]


def test_fallback_when_toolchain_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    a = TypeScriptAnalyzer()
    monkeypatch.setattr(a, "toolchain", lambda: None)
    fs = a.analyze("x.ts", "export function f() { return g(); }")
    assert fs.parse_error == FALLBACK_NOTE


def test_registry_routes_and_caches() -> None:
    cache = MemoryCache()
    reg = default_registry(cache=cache)
    files = {"a.py": "def f():\n    return 1\n", "README.md": "# hi", "b.js": "function g() {}"}
    out = reg.analyze(files)
    assert set(out) == {"a.py", "b.js"}
    assert reg.supports("x.tsx") and not reg.supports("x.go")
    assert reg.stats(out) == {"python": 1, "javascript": 1}
    again = reg.analyze(files)
    assert cache.hits == 2
    assert again["a.py"] == out["a.py"]
    changed = reg.analyze({"a.py": "def f():\n    return 2\n"})
    assert cache.hits == 2  # changed content -> new key -> no stale hit
    assert changed["a.py"].symbols


def test_registry_without_batch_method() -> None:
    class Plain:
        from sentinel.core.domain.models import Language

        language = Language.PYTHON
        extensions = (".pyx",)

        def analyze(self, path: str, source: str):  # type: ignore[no-untyped-def]
            from sentinel.analysis.ast.python_analyzer import PythonAnalyzer

            return PythonAnalyzer().analyze(path, source)

    reg = LanguageRegistry([Plain()])  # type: ignore[list-item]
    assert "m.pyx" in reg.analyze({"m.pyx": "x = 1\n"})
