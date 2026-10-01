#!/usr/bin/env python3
"""Measure how review time and memory grow with repository size (spec §42).

    python scripts/benchmark.py                 # small, medium, large; 3 runs each
    python scripts/benchmark.py --sizes small --runs 1
    python scripts/benchmark.py --json results.json   # also keep the raw numbers

For each size a synthetic Python + TypeScript repository is generated (modules that call
each other, SQL access, HTTP endpoints, tests), a small change is staged, and the full
review pipeline runs on it: diff parsing, filtering, code graph, context, every static
analyzer installed on this machine, the AI stage and verification.

The AI stage uses ``MeasuringProvider``, which answers instantly with no findings and
records how many tokens the prompt would cost. Real model latency depends on the provider
and network, so it is reported separately (not measured here). Each run happens in a fresh
subprocess so peak memory (max RSS) is per run, and caches start cold.
"""

from __future__ import annotations

import argparse
import json
import platform
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SIZES = {"small": 25, "medium": 250, "large": 1500}  # number of Python modules
TS_SHARE = 5  # one TypeScript module per this many Python modules
TEST_SHARE = 3  # one test file per this many modules
CHANGED_MODULES = 3
CHARS_PER_TOKEN = 4
KIB_PER_MIB = 1024


# --------------------------------------------------------------------------- repo generation


def python_module(index: int, modules: int) -> str:
    """A module with an endpoint, SQL access and calls into two other modules."""
    a, b = (index + 1) % modules, (index * 7 + 3) % modules
    return f'''"""Synthetic module {index}."""

from app import db
from app.mod_{a} import helper_{a}
from app.mod_{b} import score_{b}

@db.app.get("/items/{index}")
def handler_{index}(request: dict) -> list[dict]:
    rows = db.query("SELECT id, name FROM items_{index} WHERE owner = ?", (request["user"],))
    return [helper_{a}(row) for row in rows]


def helper_{index}(row: tuple) -> dict:
    return {{"id": row[0], "name": row[1], "score": score_{b}(row)}}


def score_{index}(row: tuple) -> int:
    total = 0
    for step in range(10):
        total += step * len(str(row[0]))
    return total


class Repository{index}:
    def __init__(self, conn) -> None:
        self.conn = conn

    def find(self, item_id: int) -> tuple | None:
        return self.conn.execute(
            "SELECT id, name FROM items_{index} WHERE id = ?", (item_id,)
        ).fetchone()

    def save(self, name: str) -> None:
        self.conn.execute("INSERT INTO items_{index} (name) VALUES (?)", (name,))
'''


def typescript_module(index: int) -> str:
    """An Express-style route with a parameterized query."""
    return f"""import {{ db }} from "./db";

export interface Item{index} {{ id: number; name: string }}

export async function listItems{index}(owner: string): Promise<Item{index}[]> {{
  const rows = await db.query("SELECT id, name FROM items_{index} WHERE owner = $1", [owner]);
  return rows.map((row: Item{index}) => ({{ id: row.id, name: row.name.trim() }}));
}}

export function routes{index}(app: any): void {{
  app.get("/api/items/{index}", async (req: any, res: any) => {{
    res.json(await listItems{index}(req.query.owner));
  }});
}}
"""


def test_module(index: int) -> str:
    """A pytest file for one module."""
    return f"""from app.mod_{index} import score_{index}


def test_score_{index}() -> None:
    assert score_{index}((1, "x")) == 45
"""


def generate_repo(root: Path, modules: int) -> dict[str, int]:
    """Write the repository, commit it, then stage a small change. Returns size stats."""
    files: dict[str, str] = {
        "app/__init__.py": "",
        "app/db.py": DB_MODULE,
        "web/src/db.ts": TS_DB_MODULE,
        "tsconfig.json": TSCONFIG,
    }
    for i in range(modules):
        files[f"app/mod_{i}.py"] = python_module(i, modules)
        if i % TS_SHARE == 0:
            files[f"web/src/items_{i}.ts"] = typescript_module(i)
        if i % TEST_SHARE == 0:
            files[f"tests/test_mod_{i}.py"] = test_module(i)
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(
        root, "-c", "user.name=bench", "-c", "user.email=bench@example.com", "commit", "-qm", "base"
    )
    stage_change(root)
    return {
        "files": len(files),
        "loc": sum(text.count("\n") for text in files.values()),
    }


def stage_change(root: Path) -> None:
    """A realistic small diff: new code with an injectable query and an N+1 loop."""
    for i in range(CHANGED_MODULES):
        path = root / f"app/mod_{i}.py"
        path.write_text(path.read_text() + CHANGE.format(i=i))
    ts_path = root / "web/src/items_0.ts"
    ts_path.write_text(ts_path.read_text() + TS_CHANGE)
    git(root, "add", "-A")


def git(root: Path, *args: str) -> None:
    """Run a git command in the generated repository."""
    subprocess.run(["git", *args], cwd=root, check=True)


TSCONFIG = (
    '{"compilerOptions": {"strict": true, "noEmit": true, "target": "ES2022", '
    '"module": "ESNext", "moduleResolution": "Bundler"}, "include": ["web/src"]}\n'
)
TS_DB_MODULE = (
    "export const db = { query: async (_sql: string, _args: unknown[]) => [] as any[] };\n"
)

DB_MODULE = '''"""Database access for the synthetic app."""

import sqlite3


class _App:
    def get(self, route: str):
        def register(fn):
            return fn

        return register


app = _App()
conn = sqlite3.connect(":memory:")


def query(sql: str, params: tuple = ()) -> list[tuple]:
    return conn.execute(sql, params).fetchall()
'''

TS_CHANGE = """
export async function searchItems(term: string): Promise<unknown[]> {
  return db.query(`SELECT id FROM items_0 WHERE name LIKE '%${term}%'`, []);
}
"""

CHANGE = """

def search_{i}(term: str) -> list[tuple]:
    return db.query(f"SELECT id FROM items_{i} WHERE name LIKE '%{{term}}%'")


def owners_{i}(ids: list[int]) -> list[tuple]:
    found = []
    for item_id in ids:
        found += db.query("SELECT owner FROM items_{i} WHERE id = ?", (item_id,))
    return found
"""


# --------------------------------------------------------------------------- one run


class MeasuringProvider:
    """Stands in for the AI provider: no findings, but records the prompt size."""

    name = "measuring"
    model = "none"

    def __init__(self) -> None:
        self.prompt_tokens = 0

    def review(self, request: Any) -> Any:
        """Estimate the prompt's token count and return an empty review."""
        from sentinel.ai.prompts import build_review_prompt
        from sentinel.core.domain.ai import AIReviewPayload, AIReviewResult
        from sentinel.core.domain.models import TokenUsage

        prompt = build_review_prompt(request)
        self.prompt_tokens = (len(prompt.system) + len(prompt.user)) // CHARS_PER_TOKEN
        return AIReviewResult(
            payload=AIReviewPayload(findings=[]),
            usage=TokenUsage(input_tokens=self.prompt_tokens),
            model=self.model,
            provider=self.name,
        )

    def generate_fix(self, request: Any) -> Any:
        """Not used by the benchmark."""
        raise NotImplementedError


def run_once(size: str) -> dict[str, Any]:
    """Generate one repository and review its staged change (runs in a subprocess)."""
    from sentinel.analysis.diff.git import staged_changeset
    from sentinel.bootstrap import build_orchestrator
    from sentinel.core.configuration.config import RepoConfig, Settings
    from sentinel.infrastructure.storage.cache import MemoryCache

    with tempfile.TemporaryDirectory(prefix=f"sentinel-bench-{size}-") as tmp:
        repo = Path(tmp)
        stats = generate_repo(repo, SIZES[size])
        provider = MeasuringProvider()
        started = time.perf_counter()
        changeset = staged_changeset(repo)
        orchestrator = build_orchestrator(
            Settings(provider="none"),
            RepoConfig(),
            workspace=repo,
            ai=provider,
            cache=MemoryCache(),
        )
        result = orchestrator.review(changeset, repo)
        total_ms = (time.perf_counter() - started) * 1000
    stages = {s.name.value: s.duration_ms or 0 for s in result.stages}
    return {
        **stats,
        "changed_files": len(changeset.files),
        "graph_nodes": next(s for s in result.stages if s.name.value == "build_graph").metrics.get(
            "nodes"
        ),
        "stages_ms": stages,
        "total_ms": round(total_ms),
        "prompt_tokens": provider.prompt_tokens,
        "findings": len(result.findings),
        "tools": {r.tool: r.status for r in result.analysis_runs},
        "max_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / KIB_PER_MIB),
    }


# --------------------------------------------------------------------------- driver


def measure(size: str, runs: int) -> dict[str, Any]:
    """Run ``runs`` fresh subprocesses and keep the median of each timing."""
    samples = []
    for _ in range(runs):
        out = subprocess.run(
            [sys.executable, __file__, "--one", size], capture_output=True, text=True, check=True
        )
        samples.append(json.loads(out.stdout.strip().splitlines()[-1]))
    first = samples[0]
    stage_names = list(first["stages_ms"])
    fixed = ("files", "loc", "changed_files", "graph_nodes", "prompt_tokens", "findings", "tools")
    return {
        **{key: first[key] for key in fixed},
        "stages_ms": {
            n: statistics.median(s["stages_ms"][n] for s in samples) for n in stage_names
        },
        "total_ms": statistics.median(s["total_ms"] for s in samples),
        "max_rss_mib": max(s["max_rss_mib"] for s in samples),
        "runs": runs,
    }


def markdown(results: dict[str, dict[str, Any]]) -> str:
    """The results as the tables in docs/BENCHMARKS.md."""
    sizes = list(results)
    first = results[sizes[0]]

    def row(label: str, cell: Any) -> str:
        return f"| {label} | " + " | ".join(cell(results[size]) for size in sizes) + " |"

    lines = [
        "| | " + " | ".join(sizes) + " |",
        "|---|" + "---:|" * len(sizes),
        row("Files in repository", lambda r: f"{r['files']:,}"),
        row("Lines of code", lambda r: f"{r['loc']:,}"),
        row("Files in the change", lambda r: str(r["changed_files"])),
        row("Code-graph nodes", lambda r: f"{r['graph_nodes']:,}"),
    ]
    for stage in first["stages_ms"]:
        lines.append(row(f"`{stage}` (ms)", lambda r, s=stage: f"{r['stages_ms'][s]:,.0f}"))
    lines += [
        row("**Total review latency (ms)**", lambda r: f"**{r['total_ms']:,.0f}**"),
        row("Peak memory (max RSS, MiB)", lambda r: str(r["max_rss_mib"])),
        row("AI prompt size (tokens, est.)", lambda r: f"{r['prompt_tokens']:,}"),
    ]
    tools = ", ".join(f"{tool} ({status})" for tool, status in first["tools"].items())
    machine = f"Python {platform.python_version()} on {platform.system()} {platform.machine()}"
    footer = f"Static analyzers: {tools}.  \n{machine}; median of {first['runs']} runs."
    return "\n".join(lines) + "\n\n" + footer + "\n"


def main() -> None:
    """Parse arguments and run the benchmark."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sizes", nargs="+", choices=list(SIZES), default=list(SIZES))
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--json", type=Path, help="also write raw results here")
    parser.add_argument("--one", choices=list(SIZES), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.one:
        print(json.dumps(run_once(args.one)))
        return
    results = {size: measure(size, args.runs) for size in args.sizes}
    if args.json:
        args.json.write_text(json.dumps(results, indent=2))
    print(markdown(results))


if __name__ == "__main__":
    main()
