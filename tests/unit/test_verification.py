"""Verification engine, generic checks and probes: real claims supported, wrong ones rejected."""

from __future__ import annotations

from typing import Any

import pytest

from sentinel.analysis.ast.registry import default_registry
from sentinel.analysis.diff.parser import parse_unified_diff
from sentinel.analysis.graph.builder import build_graph
from sentinel.analysis.static.probes import (
    AsyncProbe,
    AuthOrderProbe,
    ErrorHandlingProbe,
    NPlusOneProbe,
    QuadraticProbe,
    SecretProbe,
    SqlInjectionProbe,
    default_probes,
)
from sentinel.bootstrap import default_verifier
from sentinel.core.domain.graph import CodeGraph
from sentinel.core.domain.models import (
    Category,
    ChangeSet,
    CheckOutcome,
    Evidence,
    Finding,
    FindingSource,
    Severity,
    VerificationCheck,
    VerificationStatus,
)
from sentinel.core.findings.normalize import derive_tags
from sentinel.core.verification.checks import (
    CallPathCheck,
    ChangeRelevanceCheck,
    LocationCheck,
    ReachabilityCheck,
    StaticCorroborationCheck,
    StyleOnlyCheck,
    SymbolEvidenceCheck,
    TestClaimCheck,
    enclosing_label,
)
from sentinel.core.verification.engine import (
    VerificationContext,
    VerificationEngine,
    apply_verification,
    reachability,
)
from tests.helpers import build_shop

DIFF = """\
diff --git a/app/db.py b/app/db.py
--- a/app/db.py
+++ b/app/db.py
@@ -11 +11 @@ def find_user(name, password):
-    cur.execute("SELECT 1")
+    cur.execute(f"SELECT * FROM users WHERE name = '{name}' AND password = '{password}'")
"""


def _path(key: str) -> str:
    name = key.replace("__", "/")
    return name[::-1].replace("_", ".", 1)[::-1]  # app__a_py -> app/a.py


def ctx(changeset: ChangeSet | None = None, **extra: str) -> VerificationContext:
    src, res = build_shop()
    if extra:
        src = {**src, **{_path(k): v for k, v in extra.items()}}
        res = build_graph(default_registry().analyze(src))
    return VerificationContext(
        graph=res.graph,
        sources=src,
        changeset=changeset or parse_unified_diff(DIFF),
        symbols=res.files,
    )


def finding(**kw: Any) -> Finding:
    base: dict[str, Any] = {
        "category": Category.SECURITY,
        "severity": Severity.HIGH,
        "confidence": 0.7,
        "title": "t",
        "explanation": "",
        "file": "app/db.py",
        "line_start": 11,
        "line_end": 11,
        "source": FindingSource.AI,
        "origins": ["ai:test"],
    }
    base.update(kw)
    if "tags" not in kw:
        base["tags"] = derive_tags(base["title"], base["explanation"])
    return Finding(**base)


def outcome(check: VerificationCheck | None) -> str | None:
    return check.outcome.value if check else None


# ----------------------------------------------------------------- generic checks


def test_location_check_rejects_missing_files_and_lines() -> None:
    c = ctx()
    assert outcome(LocationCheck().check(finding(), c)) == "supports"
    missing = LocationCheck().check(finding(file="nope.py"), c)
    assert missing is not None and missing.decisive
    too_far = LocationCheck().check(finding(line_start=999, line_end=999), c)
    assert too_far is not None and too_far.decisive and "beyond the end" in too_far.detail
    deleted = parse_unified_diff(
        "diff --git a/gone.py b/gone.py\ndeleted file mode 100644\n"
        "--- a/gone.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n"
    )
    assert outcome(LocationCheck().check(finding(file="gone.py"), ctx(deleted))) == "neutral"


def test_change_relevance_prefers_changed_lines() -> None:
    c = ctx()
    assert outcome(ChangeRelevanceCheck().check(finding(), c)) == "supports"
    assert outcome(ChangeRelevanceCheck().check(finding(line_start=8, line_end=8), c)) == "neutral"
    assert outcome(ChangeRelevanceCheck().check(finding(line_start=16, line_end=16), c)) == (
        "contradicts"
    )


def test_symbol_evidence_rejects_hallucinated_symbols() -> None:
    c = ctx()
    ok = finding(explanation="`find_user()` uses `connect`")
    assert outcome(SymbolEvidenceCheck().check(ok, c)) == "supports"
    bad = finding(explanation="`validate_sql()` and `escape_all()` are skipped")
    res = SymbolEvidenceCheck().check(bad, c)
    assert res is not None and res.decisive and "validate_sql" in res.detail
    half = finding(explanation="`find_user()` skips `escape_all()`")
    res = SymbolEvidenceCheck().check(half, c)
    assert res is not None and res.outcome is CheckOutcome.CONTRADICTS and not res.decisive
    assert SymbolEvidenceCheck().check(finding(explanation="plain words only"), c) is None


def test_call_path_check_compares_claims_with_the_graph() -> None:
    c = ctx()
    real = finding(evidence=[Evidence(source="ai", text="login() calls authenticate()")])
    assert outcome(CallPathCheck().check(real, c)) == "supports"
    fake = finding(evidence=[Evidence(source="ai", text="find_user() calls login()")])
    assert outcome(CallPathCheck().check(fake, c)) == "contradicts"
    mixed = finding(
        evidence=[
            Evidence(source="ai", text="login() calls authenticate()"),
            Evidence(source="ai", text="connect() -> login()"),
        ]
    )
    assert outcome(CallPathCheck().check(mixed, c)) == "neutral"
    unknown = finding(evidence=[Evidence(source="ai", text="foo() calls bar()")])
    assert CallPathCheck().check(unknown, c) is None


def test_reachability_from_entry_points() -> None:
    c = ctx()
    label, path = reachability(finding(), c)
    assert label == "entrypoint" and path[0] == "POST /login"
    assert outcome(ReachabilityCheck().check(finding(), c)) == "supports"
    dead = finding(file="app/services.py", line_start=15, line_end=15)
    assert reachability(dead, c)[0] == "unreachable"
    assert outcome(ReachabilityCheck().check(dead, c)) == "contradicts"
    module_level = finding(line_start=1, line_end=1)
    assert reachability(module_level, c)[0] == "unknown"
    assert ReachabilityCheck().check(module_level, c) is None


def test_static_corroboration_requires_matching_tags() -> None:
    static = finding(
        source=FindingSource.STATIC_ANALYZER,
        origins=["ruff:S608"],
        tags=["sql-injection"],
        line_start=12,
        line_end=12,
    )
    c = ctx()
    c.static_findings = [static]
    res = StaticCorroborationCheck().check(finding(title="SQL injection"), c)
    assert res is not None and res.weight == 2.0 and "ruff:S608" in res.detail
    assert (
        StaticCorroborationCheck().check(
            finding(title="SQL injection", line_start=20, line_end=20), c
        )
        is None
    )
    assert StaticCorroborationCheck().check(finding(title="N+1 query in loop"), c) is None


def test_missing_test_claims_are_checked_against_the_graph() -> None:
    c = ctx()
    claim = finding(category=Category.TESTS, title="find_user has no tests")
    assert outcome(TestClaimCheck().check(claim, c)) == "supports"
    covered = finding(
        category=Category.TESTS,
        title="orders_for is untested",
        file="app/services.py",
        line_start=7,
        line_end=7,
    )
    assert outcome(TestClaimCheck().check(covered, c)) == "neutral"
    with_test_change = parse_unified_diff(
        DIFF + "diff --git a/tests/test_services.py b/tests/test_services.py\n"
        "--- a/tests/test_services.py\n+++ b/tests/test_services.py\n@@ -5 +5 @@\n-x\n+y\n"
    )
    res = TestClaimCheck().check(covered, ctx(with_test_change))
    assert res is not None and res.decisive
    assert TestClaimCheck().check(finding(title="SQL injection"), c) is None


def test_style_remarks_filed_as_bugs_are_rejected() -> None:
    c = ctx()
    res = StyleOnlyCheck().check(finding(category=Category.BUG, title="Rename variable cur"), c)
    assert res is not None and res.decisive
    soft = StyleOnlyCheck().check(
        finding(category=Category.BUG, title="Minor issue", explanation="Improve readability."), c
    )
    assert soft is not None and not soft.decisive
    assert StyleOnlyCheck().check(finding(category=Category.STYLE, title="Rename"), c) is None
    assert StyleOnlyCheck().check(finding(title="SQL injection, also naming"), c) is None


def test_enclosing_label_names_functions_and_module_level() -> None:
    c = ctx()
    assert enclosing_label(c.graph.enclosing("app/db.py", 11)) == "find_user()"
    assert enclosing_label(None) == "module level"


# ----------------------------------------------------------------- probes

ASYNC_SRC = (
    """\
import time
async def notify(u):
    return u
async def handler(u):
    time.sleep(1)
    notify(u)
    await notify(u)
def sync(u):
    time.sleep(1)
def pairs(a, b):
    for x in a:
        for y in b:
            if x == y:
                return x
def flat(a):
    for x in a:
        print(x)
def swallow():
    try:
        risky()
    except Exception:
        pass
def handled():
    try:
        risky()
    except ValueError as e:
        log(e)
KEY = "sk_live_"""
    + "b" * 24
    + """"
TOKEN = os.environ["TOKEN"]
"""
)


def test_sql_probe_variants() -> None:
    p = SqlInjectionProbe()
    c = ctx()
    res = p.check(finding(title="SQL injection"), c)
    assert res is not None and res.outcome is CheckOutcome.SUPPORTS
    assert "POST /login" in res.detail
    res = p.check(finding(title="SQL injection", line_start=17, line_end=17), c)
    assert res is not None and res.decisive
    none = p.check(finding(title="SQL injection", line_start=4, line_end=4), c)
    assert outcome(none) == "contradicts" and none is not None and not none.decisive
    cast = ctx(
        app__cast_py=(
            "def get(cur, raw):\n    uid = int(raw)\n"
            "    cur.execute(f'SELECT * FROM t WHERE id = {uid}')\n"
        )
    )
    res = p.check(
        finding(title="SQL injection", file="app/cast.py", line_start=3, line_end=3), cast
    )
    assert res is not None and "cast" in res.detail
    const = ctx(app__const_py="def q(cur):\n    cur.execute('SELECT 1')\n")
    res = p.check(
        finding(title="SQL injection", file="app/const.py", line_start=2, line_end=2), const
    )
    assert res is not None and res.decisive and "constant" in res.detail
    assert p.check(finding(title="N+1"), c) is None


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("await db.query(`SELECT * FROM u WHERE id = ${id}`);", "supports"),
        ("await prisma.$queryRaw`SELECT * FROM u WHERE id = ${id}`;", "contradicts"),
        ("await db.query('SELECT * FROM u WHERE id = $1', [id]);", "contradicts"),
        ("const x = 1;", None),
    ],
)
def test_sql_probe_on_javascript_queries(line: str, expected: str | None) -> None:
    c = ctx(src__q_ts=f"export async function q(id) {{\n  {line}\n}}\n")
    res = SqlInjectionProbe().check(
        finding(title="SQL injection", file="src/q.ts", line_start=2, line_end=2), c
    )
    assert outcome(res) == expected


def test_n_plus_one_probe_requires_a_query_inside_a_loop() -> None:
    c = ctx()
    p = NPlusOneProbe()
    res = p.check(
        finding(title="N+1 queries", file="app/services.py", line_start=10, line_end=10), c
    )
    assert outcome(res) == "supports"
    res = p.check(finding(title="N+1 queries"), c)
    assert outcome(res) == "contradicts" and res is not None and "not inside a loop" in res.detail
    res = p.check(finding(title="N+1 queries", file="app/api.py", line_start=22, line_end=22), c)
    assert outcome(res) == "contradicts"
    assert p.check(finding(title="SQL injection"), c) is None


def test_async_probe_confirms_blocking_calls_and_missing_awaits() -> None:
    c = ctx(app__a_py=ASYNC_SRC)
    p = AsyncProbe()
    blocking = finding(
        title="time.sleep blocks the event loop", file="app/a.py", line_start=5, line_end=5
    )
    assert outcome(p.check(blocking, c)) == "supports"
    not_async = blocking.model_copy(update={"line_start": 9, "line_end": 9})
    res = p.check(not_async, c)
    assert res is not None and res.decisive
    missing = finding(title="notify() is never awaited", file="app/a.py", line_start=6, line_end=6)
    assert outcome(p.check(missing, c)) == "supports"
    awaited = missing.model_copy(update={"line_start": 7, "line_end": 7})
    res = p.check(awaited, c)
    assert res is not None and res.decisive
    assert p.check(finding(title="missing await", file="src/x.ts"), c) is None


def test_quadratic_probe_requires_pairwise_nested_loops() -> None:
    c = ctx(app__a_py=ASYNC_SRC)
    p = QuadraticProbe()
    assert (
        outcome(
            p.check(
                finding(title="O(n^2) nested loop", file="app/a.py", line_start=12, line_end=12), c
            )
        )
        == "supports"
    )
    assert (
        outcome(
            p.check(finding(title="quadratic loop", file="app/a.py", line_start=17, line_end=17), c)
        )
        == "contradicts"
    )


def test_secret_probe_tells_literals_from_environment_reads() -> None:
    c = ctx(app__a_py=ASYNC_SRC)
    p = SecretProbe()
    assert (
        outcome(
            p.check(
                finding(title="Hard-coded secret key", file="app/a.py", line_start=28, line_end=28),
                c,
            )
        )
        == "supports"
    )
    res = p.check(
        finding(title="Hard-coded secret token", file="app/a.py", line_start=29, line_end=29), c
    )
    assert res is not None and res.decisive


def test_error_handling_probe_finds_silent_handlers() -> None:
    c = ctx(app__a_py=ASYNC_SRC)
    p = ErrorHandlingProbe()
    assert (
        outcome(
            p.check(
                finding(
                    title="Exception silently swallowed",
                    file="app/a.py",
                    line_start=20,
                    line_end=20,
                ),
                c,
            )
        )
        == "supports"
    )
    res = p.check(
        finding(
            title="Missing error handling for risky()", file="app/a.py", line_start=25, line_end=25
        ),
        c,
    )
    assert outcome(res) == "contradicts"


AUTH_SRC = """\
def admin_panel(request):
    if is_admin(request.user):
        user = verify_token(request.headers["token"])
        return render(user)

def good_panel(request):
    user = verify_token(request.headers["token"])
    if is_admin(user):
        return render(user)

def open_panel(request):
    return render(None)
"""


def test_auth_probe_checks_order_and_missing_authorization() -> None:
    c = ctx(app__admin_py=AUTH_SRC)
    p = AuthOrderProbe()
    before = finding(
        title="Authorization check runs before authentication",
        file="app/admin.py",
        line_start=2,
        line_end=2,
    )
    assert outcome(p.check(before, c)) == "supports"
    fine = before.model_copy(update={"line_start": 8, "line_end": 8})
    res = p.check(fine, c)
    assert res is not None and res.decisive
    missing = finding(
        title="Missing authorization check", file="app/admin.py", line_start=8, line_end=8
    )
    assert outcome(p.check(missing, c)) == "contradicts"
    missing_open = missing.model_copy(update={"line_start": 12, "line_end": 12})
    assert p.check(missing_open, c) is None  # not reachable from an entry point


def test_default_probes_listed() -> None:
    assert {p.name for p in default_probes()} >= {"probe:sql-injection", "probe:auth"}


# ----------------------------------------------------------------- engine


class _Boom:
    name = "boom"

    def check(self, finding: Finding, ctx: VerificationContext) -> VerificationCheck | None:
        raise RuntimeError("bad check")


def test_engine_thresholds_and_crash_isolation() -> None:
    c = VerificationContext(graph=CodeGraph(), sources={}, changeset=ChangeSet())
    engine = VerificationEngine([_Boom()])
    res = engine.verify(finding(), c)
    assert res.status is VerificationStatus.UNCERTAIN
    assert res.checks[0].outcome is CheckOutcome.SKIPPED

    def decide(*checks: tuple[str, float, bool]) -> VerificationStatus:
        items = [
            VerificationCheck(name=f"c{i}", outcome=CheckOutcome(o), detail=o, weight=w, decisive=d)
            for i, (o, w, d) in enumerate(checks)
        ]
        return VerificationEngine._decide(items, "unknown", []).status

    assert decide(("supports", 2.0, False)) is VerificationStatus.SUPPORTED
    assert decide(("supports", 1.0, False)) is VerificationStatus.LIKELY
    assert decide(("supports", 1.0, False), ("contradicts", 1.0, False)) is (
        VerificationStatus.UNCERTAIN
    )
    assert decide(("contradicts", 1.0, False)) is VerificationStatus.REJECTED
    assert decide(("supports", 5.0, False), ("contradicts", 0.1, True)) is (
        VerificationStatus.REJECTED
    )


def test_apply_verification_adjusts_confidence_and_source() -> None:
    c = ctx()
    f = finding(title="SQL injection in find_user", confidence=0.5)
    apply_verification(f, default_verifier().verify(f, c))
    assert f.source is FindingSource.VERIFIED and f.confidence >= 0.8
    bad = finding(title="SQL injection", file="ghost.py", confidence=0.9)
    apply_verification(bad, default_verifier().verify(bad, c))
    assert bad.confidence <= 0.2
    static = finding(source=FindingSource.STATIC_ANALYZER, origins=["ruff:S608"], confidence=0.8)
    apply_verification(static, VerificationEngine.deterministic(static, c))
    assert static.confidence == 0.8 and static.verification is not None
