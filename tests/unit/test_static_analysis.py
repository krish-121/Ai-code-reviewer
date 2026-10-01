from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from sentinel.analysis.ast.registry import default_registry
from sentinel.analysis.static.base import find_tool, relpath, run_tool, scrubbed_env
from sentinel.analysis.static.builtin_security import BuiltinAnalyzer
from sentinel.analysis.static.python_patterns import dynamic_sql_kind
from sentinel.analysis.static.js_tools import ESLintAnalyzer, TscAnalyzer, _config_source
from sentinel.analysis.static.python_tools import BanditAnalyzer, MypyAnalyzer, RuffAnalyzer
from sentinel.analysis.static.runner import StaticAnalysisRunner, default_analyzers
from sentinel.core.domain.models import AnalysisRun, Category, Language, Severity
from sentinel.core.domain.ports import StaticAnalysisOutput
from tests.helpers import SHOP

WS = Path("/repo")


def rules(src: str, path: str = "m.py") -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for f in BuiltinAnalyzer.analyze_source(path, src):
        out.setdefault(f.rule_id or "", []).append(f.line_start)
    return out


# ----------------------------------------------------------------- builtin python rules


def test_sql_injection_variants() -> None:
    src = """\
def a(cur, name):
    cur.execute(f"SELECT * FROM t WHERE n = '{name}'")
def b(cur, name):
    q = "SELECT * FROM t WHERE n = '" + name + "'"
    cur.execute(q)
def c(cur, name):
    cur.execute("SELECT * FROM t WHERE n = '%s'" % name)
def d(cur, name):
    cur.execute("SELECT * FROM t WHERE n = '{}'".format(name))
def safe(cur, name):
    cur.execute("SELECT * FROM t WHERE n = ?", (name,))
def safe2(cur):
    cur.execute("SELECT " + "1")
def e(session, name):
    session.execute(text(f"DELETE FROM t WHERE n = {name}"))
"""
    assert rules(src)["sentinel/sql-injection"] == [2, 5, 7, 9, 15]


def test_injection_deserialization_tls_and_crypto() -> None:
    src = """\
import os, subprocess, pickle, yaml, hashlib, requests
def run(cmd, data, pw):
    os.system("ls " + cmd)
    subprocess.run(cmd, shell=True)
    subprocess.run(["ls", cmd])
    eval(data)
    eval("1 + 1")
    pickle.loads(data)
    yaml.load(data)
    yaml.load(data, Loader=yaml.SafeLoader)
    requests.get("https://x", verify=False)
def hash_password(pw):
    return hashlib.md5(pw.encode()).hexdigest()
def checksum(blob):
    return hashlib.md5(blob).hexdigest()
"""
    r = rules(src)
    assert r["sentinel/command-injection"] == [3, 4]
    assert r["sentinel/code-injection"] == [6]
    assert r["sentinel/unsafe-deserialization"] == [8]
    assert r["sentinel/unsafe-yaml"] == [9]
    assert r["sentinel/tls-verify-disabled"] == [11]
    assert r["sentinel/weak-hash"] == [13]


def test_async_rules() -> None:
    src = """\
import time, asyncio, requests
async def notify(user):
    await asyncio.sleep(0)
async def handler(user):
    time.sleep(1)
    requests.get("https://example.com")
    notify(user)
    await notify(user)
    asyncio.create_task(notify(user))
def sync(user):
    time.sleep(1)
class Svc:
    async def send(self):
        return 1
    async def go(self):
        self.send()
"""
    r = rules(src)
    assert r["sentinel/blocking-in-async"] == [5, 6]
    assert r["sentinel/missing-await"] == [7, 16]


def test_performance_rules() -> None:
    src = """\
def orders(conn, ids):
    for i in ids:
        conn.execute("SELECT * FROM o WHERE id = ?", (i,))
        conn.execute("SELECT * FROM p WHERE id = ?", (i,))
    return 1
def dupes(a, b):
    out = []
    for x in a:
        for y in b:
            if x.id == y.id:
                out.append(x)
    return out
def fine(a):
    for i in range(10):
        for j in range(10):
            if i == j:
                pass
"""
    r = rules(src)
    assert r["sentinel/n-plus-one"] == [3]  # reported once per loop
    assert r["sentinel/quadratic-loop"] == [9]


def test_swallowed_exception() -> None:
    src = """\
def a():
    try:
        x()
    except Exception:
        pass
def b():
    try:
        x()
    except ValueError:
        pass
def c():
    try:
        x()
    except:
        "ignored"
"""
    assert rules(src)["sentinel/swallowed-exception"] == [4, 14]


def test_syntax_error_yields_nothing() -> None:
    assert BuiltinAnalyzer.analyze_source("bad.py", "def (:") == []


def test_dynamic_sql_kind_helpers() -> None:
    import ast

    assert dynamic_sql_kind(ast.parse('f"x"').body[0].value) is None  # type: ignore[attr-defined]
    assert dynamic_sql_kind(None) is None
    node = ast.parse("q").body[0].value  # type: ignore[attr-defined]
    assigned = {"q": ast.parse('"a" + b').body[0].value}  # type: ignore[attr-defined]
    assert dynamic_sql_kind(node, assigned) == "string concatenation (via `q`)"


# ----------------------------------------------------------------- builtin JS rules


def test_js_rules() -> None:
    src = """\
// db.query(`SELECT ${x}`) in a comment is ignored
await db.query(`SELECT * FROM users WHERE id = ${id}`);
await db.query("SELECT * FROM users WHERE id = " + id);
await db.query("SELECT * FROM users WHERE id = $1", [id]);
eval(userCode);
exec(`rm -rf ${dir}`);
el.innerHTML = html;
el.innerHTML = "<b>static</b>";
const agent = new https.Agent({ rejectUnauthorized: false });
"""
    r = rules(src, "a.ts")
    assert r["sentinel/sql-injection"] == [2, 3]
    assert r["sentinel/code-injection"] == [5]
    assert r["sentinel/command-injection"] == [6]
    assert r["sentinel/xss"] == [7]
    assert r["sentinel/tls-verify-disabled"] == [9]


def test_builtin_run_includes_js_db_in_loop(tmp_path: Path) -> None:
    (tmp_path / "svc.js").write_text(
        "async function load(ids) {\n  for (const id of ids) {\n"
        "    await db.query('SELECT * FROM t WHERE id = $1', [id]);\n  }\n}\n"
    )
    out = BuiltinAnalyzer(default_registry()).run(tmp_path, ["svc.js", "missing.py"])
    assert out.run.status == "ok"
    assert [f.rule_id for f in out.findings] == ["sentinel/n-plus-one"]


# ----------------------------------------------------------------- tool output parsing


def test_ruff_parse() -> None:
    out = json.dumps(
        [
            {
                "code": "S608",
                "message": "Possible SQL injection",
                "filename": "/repo/app/db.py",
                "location": {"row": 11, "column": 5},
                "end_location": {"row": 12, "column": 1},
            },
            {
                "code": "F401",
                "message": "unused import",
                "filename": "/repo/app/x.py",
                "location": {"row": 1, "column": 1},
                "end_location": {"row": 1, "column": 9},
            },
            {
                "code": "ASYNC251",
                "message": "blocking sleep",
                "filename": "app/y.py",
                "location": {"row": 3, "column": 1},
            },
            {
                "code": "ZZZ1",
                "message": "unknown",
                "filename": "app/z.py",
                "location": {"row": 2, "column": 1},
            },
        ]
    )
    f = RuffAnalyzer.parse(out, WS)
    assert [x.file for x in f] == ["app/db.py", "app/x.py", "app/y.py", "app/z.py"]
    assert f[0].severity is Severity.HIGH and f[0].tags == ["sql-injection"]
    assert (f[0].line_start, f[0].line_end) == (11, 12)
    assert f[1].category is Category.STYLE
    assert f[2].category is Category.PERFORMANCE
    assert f[3].severity is Severity.LOW
    assert RuffAnalyzer.parse("not json", WS) == []


def test_mypy_parse_json_and_text() -> None:
    lines = "\n".join(
        [
            json.dumps(
                {
                    "file": "a.py",
                    "line": 3,
                    "message": "Incompatible return",
                    "code": "return-value",
                    "severity": "error",
                }
            ),
            json.dumps(
                {
                    "file": "a.py",
                    "line": 1,
                    "message": "untyped",
                    "code": "no-untyped-def",
                    "severity": "error",
                }
            ),
            json.dumps(
                {"file": "a.py", "line": 1, "message": "note", "code": "misc", "severity": "note"}
            ),
            'b.py:7:5: error: Argument 1 to "f" has incompatible type "str"  [arg-type]',
            "{broken json",
            "garbage line",
        ]
    )
    f = MypyAnalyzer.parse(lines, WS)
    assert [(x.file, x.line_start, x.rule_id) for x in f] == [
        ("a.py", 3, "mypy/return-value"),
        ("b.py", 7, "mypy/arg-type"),
    ]


def test_bandit_parse() -> None:
    data = {
        "results": [
            {
                "test_id": "B608",
                "issue_severity": "MEDIUM",
                "issue_confidence": "LOW",
                "issue_text": "Possible SQL injection",
                "filename": "./app/db.py",
                "line_number": 11,
                "line_range": [11, 12],
                "issue_cwe": {"id": 89},
            },
            {
                "test_id": "B101",
                "issue_severity": "LOW",
                "issue_confidence": "HIGH",
                "issue_text": "assert",
                "filename": "t.py",
                "line_number": 1,
            },
        ]
    }
    f = BanditAnalyzer.parse("[main] INFO noise\n" + json.dumps(data), WS)
    assert len(f) == 1
    assert f[0].file == "app/db.py" and f[0].severity is Severity.HIGH
    assert "cwe-89" in f[0].tags and f[0].line_end == 12
    assert BanditAnalyzer.parse("", WS) == []


def test_eslint_parse_and_config() -> None:
    data = [
        {
            "filePath": "/repo/src/a.js",
            "messages": [
                {"ruleId": "no-eval", "line": 4, "message": "eval is harmful"},
                {"ruleId": None, "fatal": True, "line": 1, "message": "Parsing error"},
                {"ruleId": "no-await-in-loop", "line": 9, "endLine": 9, "message": "await in loop"},
            ],
        }
    ]
    f = ESLintAnalyzer.parse(json.dumps(data), WS)
    assert [(x.rule_id, x.category) for x in f] == [
        ("eslint/no-eval", Category.SECURITY),
        ("eslint/no-await-in-loop", Category.PERFORMANCE),
    ]
    assert "createRequire" in _config_source(None)
    assert "@typescript-eslint" in _config_source(Path("/x/@typescript-eslint/parser"))


def test_tsc_parse() -> None:
    out = (
        "src/a.ts(3,7): error TS2304: Cannot find name 'foo'.\n"
        "src/b.ts(1,1): error TS2345: Argument of type 'string' is not assignable.\n"
        "some summary line\n"
    )
    f = TscAnalyzer.parse(out, WS)
    assert [(x.file, x.severity) for x in f] == [
        ("src/a.ts", Severity.HIGH),
        ("src/b.ts", Severity.MEDIUM),
    ]


# ----------------------------------------------------------------- real tools (if installed)


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff not installed")
def test_ruff_real_run() -> None:
    out = RuffAnalyzer().run(SHOP, ["app/db.py"])
    assert out.run.status == "ok"
    assert any(f.rule_id == "ruff/S608" and f.line_start == 11 for f in out.findings)


@pytest.mark.skipif(shutil.which("mypy") is None, reason="mypy not installed")
def test_mypy_real_run(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("def f(x: int) -> str:\n    return x\n")
    out = MypyAnalyzer().run(tmp_path, ["m.py"])
    assert [f.rule_id for f in out.findings] == ["mypy/return-value"]


@pytest.mark.skipif(shutil.which("eslint") is None, reason="eslint not installed")
def test_eslint_real_run(tmp_path: Path) -> None:
    (tmp_path / "a.js").write_text("export function f(x) { return eval(x); }\n")
    (tmp_path / "b.ts").write_text("export const y: number = 1;\n")
    out = ESLintAnalyzer().run(tmp_path, ["a.js", "b.ts"])
    assert out.run.status == "ok", out.run
    assert [f.rule_id for f in out.findings] == ["eslint/no-eval"]
    only_ts = ESLintAnalyzer().run(tmp_path, ["b.ts"])
    assert only_ts.run.status == "unavailable"


def test_tools_report_unavailable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import sentinel.analysis.static.js_tools as js
    import sentinel.analysis.static.python_tools as py

    monkeypatch.setattr(py, "find_tool", lambda *_a, **_k: None)
    monkeypatch.setattr(js, "find_tool", lambda *_a, **_k: None)
    for analyzer in (
        RuffAnalyzer(),
        MypyAnalyzer(),
        BanditAnalyzer(),
        ESLintAnalyzer(),
        TscAnalyzer(),
    ):
        out = analyzer.run(tmp_path, ["x.py", "y.ts"])
        assert out.run.status == "unavailable"
        assert not analyzer.is_available()


def test_tsc_requires_tsconfig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sentinel.analysis.static.js_tools as js

    monkeypatch.setattr(js, "find_tool", lambda *_a, **_k: "/usr/bin/tsc")
    out = TscAnalyzer().run(tmp_path, ["a.ts"])
    assert "tsconfig" in out.run.detail


# ----------------------------------------------------------------- runner & plumbing


class _Boom:
    name = "boom"
    languages = frozenset({Language.PYTHON})

    def is_available(self) -> bool:
        return True

    def run(self, workspace: Path, files: list[str]) -> StaticAnalysisOutput:
        raise RuntimeError("kaboom")


class _Echo:
    name = "echo"
    languages = frozenset({Language.TYPESCRIPT})

    def is_available(self) -> bool:
        return True

    def run(self, workspace: Path, files: list[str]) -> StaticAnalysisOutput:
        return StaticAnalysisOutput(AnalysisRun(tool="echo", status="ok", detail=",".join(files)))


def test_runner_isolates_crashes_and_routes_languages() -> None:
    runner = StaticAnalysisRunner([_Boom(), _Echo(), BuiltinAnalyzer()], disabled=["sentinel"])
    findings, runs = runner.run(Path("."), ["a.py", "b.ts", "c.md"])
    by_tool = {r.tool: r for r in runs}
    assert by_tool["boom"].status == "failed" and "kaboom" in by_tool["boom"].detail
    assert by_tool["echo"].detail == "b.ts"
    assert by_tool["sentinel"].status == "skipped"
    assert findings == []
    assert StaticAnalysisRunner([_Echo()]).run(Path("."), ["a.py"]) == ([], [])


def test_default_analyzers_names() -> None:
    names = [a.name for a in default_analyzers()]
    assert names == ["sentinel", "ruff", "mypy", "bandit", "eslint", "tsc"]


def test_base_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTINEL_CLAUDE_KEY", "secret")
    assert "SENTINEL_CLAUDE_KEY" not in scrubbed_env()
    assert relpath("/repo/a/b.py", Path("/repo")) == "a/b.py"
    assert relpath("./a.py", Path("/repo")) == "a.py"
    assert relpath("/elsewhere/x.py", Path("/repo")) == "/elsewhere/x.py"
    bin_dir = tmp_path / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    tool = bin_dir / "mytool"
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    assert find_tool("mytool", tmp_path) == str(tool)
    res = run_tool(["sleep", "5"], tmp_path, timeout_s=1)
    assert res.timed_out
