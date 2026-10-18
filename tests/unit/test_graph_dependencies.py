"""Regressions for graph identity, global dependencies and independent UI projections."""

from __future__ import annotations

import pytest

from sentinel.analysis.ast.registry import default_registry
from sentinel.analysis.diff.parser import parse_unified_diff
from sentinel.analysis.graph.architecture import architecture_subgraph
from sentinel.analysis.graph.builder import build_graph
from sentinel.analysis.graph.context import ContextEngine
from sentinel.core.domain.graph import CodeGraph, EdgeKind, NodeKind, node_id


def graph_for(sources: dict[str, str]):
    files = default_registry().analyze(sources)
    assert all(not fs.parse_error for fs in files.values())
    return build_graph(files).graph, files


@pytest.mark.parametrize(
    ("path", "source"),
    [("config.py", "LIMIT: int = 10\n"), ("config.ts", "export const LIMIT = 10;\n")],
)
def test_module_and_variable_definitions_are_preserved(path: str, source: str) -> None:
    graph, _ = graph_for({path: source})
    module = node_id(NodeKind.MODULE, path, "<module>")
    variable = node_id(NodeKind.VARIABLE, path, "LIMIT")
    assert graph.node(module) is not None
    assert graph.node(variable) is not None
    assert [e.target for e in graph.out_edges(module, [EdgeKind.DEFINES])] == [variable]
    assert not graph.is_entrypoint(graph.node(variable))


@pytest.mark.parametrize(
    ("extension", "config", "consumer"),
    [
        (
            "py",
            "LIMIT = 10\n",
            "from config import LIMIT as maximum\ndef main():\n    return maximum\n",
        ),
        (
            "ts",
            "export const LIMIT = 10;\n",
            "import {LIMIT as maximum} from './config';\nexport function main() { return maximum; }\n",
        ),
        (
            "js",
            "export const LIMIT = 10;\n",
            "import {LIMIT as maximum} from './config';\nexport function main() { return maximum; }\n",
        ),
    ],
)
def test_imported_variables_link_to_their_real_definition(
    extension: str, config: str, consumer: str
) -> None:
    graph, _ = graph_for({f"config.{extension}": config, f"app.{extension}": consumer})
    caller = node_id(NodeKind.FUNCTION, f"app.{extension}", "main")
    variable = node_id(NodeKind.VARIABLE, f"config.{extension}", "LIMIT")
    assert [e.target for e in graph.out_edges(caller, [EdgeKind.READS])] == [variable]


@pytest.mark.parametrize(
    ("extension", "consumer"),
    [
        ("py", "import config as cfg\ndef main():\n    return cfg.LIMIT\n"),
        ("ts", "import * as cfg from './config';\nexport function main() { return cfg.LIMIT; }\n"),
    ],
)
def test_namespace_import_variable_reads(extension: str, consumer: str) -> None:
    config = "LIMIT = 10\n" if extension == "py" else "export const LIMIT = 10;\n"
    graph, _ = graph_for({f"config.{extension}": config, f"app.{extension}": consumer})
    main = node_id(NodeKind.FUNCTION, f"app.{extension}", "main")
    assert [graph.node(e.target).name for e in graph.out_edges(main, [EdgeKind.READS])] == ["LIMIT"]


@pytest.mark.parametrize(
    ("path", "source"),
    [
        (
            "app.py",
            "LIMIT = 10\ndef parameter(LIMIT):\n    return LIMIT\ndef local():\n    LIMIT = 4\n    return LIMIT\n",
        ),
        (
            "app.ts",
            "const LIMIT = 10;\nfunction parameter(LIMIT: number) { return LIMIT; }\nfunction local() { const LIMIT = 4; return LIMIT; }\n",
        ),
    ],
)
def test_shadowed_names_do_not_create_global_access_edges(path: str, source: str) -> None:
    graph, _ = graph_for({path: source})
    for name in ("parameter", "local"):
        assert graph.out_edges(node_id(NodeKind.FUNCTION, path, name), [EdgeKind.READS]) == []


@pytest.mark.parametrize(
    ("path", "source"),
    [
        ("app.py", "COUNT = 0\ndef increment():\n    global COUNT\n    COUNT += 1\n"),
        ("app.ts", "let COUNT = 0;\nfunction increment() { COUNT++; }\n"),
    ],
)
def test_increment_records_both_read_and_write(path: str, source: str) -> None:
    graph, _ = graph_for({path: source})
    increment = node_id(NodeKind.FUNCTION, path, "increment")
    variable = node_id(NodeKind.VARIABLE, path, "COUNT")
    assert {(e.kind, e.target) for e in graph.out_edges(increment)} == {
        (EdgeKind.READS, variable),
        (EdgeKind.WRITES, variable),
    }


def test_nested_definitions_belong_to_their_enclosing_function() -> None:
    graph, _ = graph_for(
        {"app.py": "def outer():\n    def inner():\n        return 1\n    return inner()\n"}
    )
    outer = node_id(NodeKind.FUNCTION, "app.py", "outer")
    inner = node_id(NodeKind.FUNCTION, "app.py", "outer.inner")
    assert inner in [e.target for e in graph.out_edges(outer, [EdgeKind.DEFINES])]


def test_same_route_in_different_files_keeps_separate_handlers() -> None:
    graph, _ = graph_for(
        {
            "one.py": '@app.get("/health")\ndef health():\n    return 1\n',
            "two.py": '@app.get("/health")\ndef health():\n    return 2\n',
        }
    )
    endpoints = [n for n in graph.nodes if n.kind is NodeKind.ENDPOINT]
    assert len(endpoints) == 2
    for endpoint in endpoints:
        targets = [graph.node(e.target) for e in graph.out_edges(endpoint.id, [EdgeKind.ROUTES])]
        assert len(targets) == 1 and targets[0].file == endpoint.file


def test_subgraph_changes_never_mutate_the_full_graph() -> None:
    graph, _ = graph_for({"app.py": "def main():\n    return 1\n"})
    original = graph.to_dict()
    main = node_id(NodeKind.FUNCTION, "app.py", "main")
    sub = architecture_subgraph(graph, {main})
    assert sub.node(main).meta["changed"] == "true"
    assert graph.to_dict() == original
    sub.node(main).meta["extra"] = "independent"
    assert "extra" not in graph.node(main).meta


def test_architecture_budget_is_hard_and_output_is_deterministic() -> None:
    graph, _ = graph_for({"app.py": "\n".join(f"def fn{i}(): return {i}" for i in range(10))})
    focus = {n.id for n in graph.nodes if n.kind is NodeKind.FUNCTION}
    first = architecture_subgraph(graph, focus, max_nodes=3).to_dict()
    assert len(first["nodes"]) == 3
    assert architecture_subgraph(graph, focus, max_nodes=3).to_dict() == first


def test_changed_constant_includes_unchanged_consumer_and_source_in_context() -> None:
    sources = {
        "config.py": "LIMIT: int = 10\n",
        "app.py": "from config import LIMIT\ndef main():\n    return LIMIT\n",
    }
    graph, files = graph_for(sources)
    diff = parse_unified_diff(
        "diff --git a/config.py b/config.py\n--- a/config.py\n+++ b/config.py\n@@ -1 +1 @@\n-LIMIT: int = 5\n+LIMIT: int = 10\n"
    )
    bundle = ContextEngine(graph, sources, files).build(diff)
    assert bundle.changed_symbols[0].kind is NodeKind.VARIABLE
    assert any(b.file == "app.py" and "return LIMIT" in b.code for b in bundle.blocks)
    assert any(n.name == "LIMIT" for n in bundle.subgraph.nodes)
    assert any(n.name == "main" for n in bundle.subgraph.nodes)


def test_variable_relationships_survive_graph_serialization() -> None:
    graph, _ = graph_for({"app.py": "LIMIT = 10\ndef main():\n    return LIMIT\n"})
    restored = CodeGraph.from_dict(graph.to_dict())
    assert restored.to_dict() == graph.to_dict()


def test_unknown_imports_and_locals_are_not_guessed() -> None:
    graph, _ = graph_for(
        {
            "app.py": "from external import LIMIT\ndef main():\n    return LIMIT\n",
            "other.py": "LIMIT = 10\n",
        }
    )
    main = node_id(NodeKind.FUNCTION, "app.py", "main")
    assert graph.out_edges(main, [EdgeKind.READS]) == []
