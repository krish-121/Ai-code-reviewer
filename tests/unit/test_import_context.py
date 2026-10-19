"""Imported data contracts reach review prompts without guessing or escaping budgets."""

import pytest

from sentinel.analysis.ast.registry import default_registry
from sentinel.analysis.diff.parser import parse_unified_diff
from sentinel.analysis.graph.builder import build_graph
from sentinel.analysis.graph.context import ContextEngine
from sentinel.analysis.graph.import_context import imported_data_nodes
from sentinel.core.fixes.patch import unified_diff


@pytest.mark.parametrize("language", ["python", "typescript", "javascript"])
def test_named_data_imports_include_the_correct_definition(language: str) -> None:
    if language == "python":
        source = "from models import CartLine as Line\ndef price(line: Line):\n    return int(line.amount)\n"
        model = "class CartLine:\n    amount: int\n"
        extension = "py"
    else:
        extension = "ts" if language == "typescript" else "js"
        source = (
            "import { CartLine as Line } from './models';\nexport function price(line) { return Number(line.amount); }\n"
            if language == "typescript"
            else "const { CartLine: Line } = require('./models');\nfunction price(line) { return Number(line.amount); }\n"
        )
        model = "export class CartLine { amount = 1; }\n"
    changed = f"service.{extension}"
    sources = {
        changed: source,
        f"models.{extension}": model,
        f"unrelated.{extension}": model.replace("amount", "other"),
    }
    extracted = default_registry().analyze(sources)
    graph = build_graph(extracted).graph
    changes = parse_unified_diff(unified_diff({changed: ""}, {changed: source}))

    bundle = ContextEngine(graph, sources, extracted).build(changes)

    definitions = [block for block in bundle.blocks if block.kind == "dependency"]
    assert any(
        block.file == f"models.{extension}" and "amount" in block.code for block in definitions
    )
    assert not any(block.file == f"unrelated.{extension}" for block in bundle.blocks)


def test_imported_data_obeys_redaction_and_the_context_budget() -> None:
    secret = "ghp_" + "Z" * 36
    source = "from models import CartLine\ndef price(line: CartLine):\n    return line.amount\n"
    sources = {
        "service.py": source,
        "models.py": f"class CartLine:\n    amount: int\n    token = '{secret}'\n",
    }
    extracted = default_registry().analyze(sources)
    graph = build_graph(extracted).graph
    changes = parse_unified_diff(unified_diff({"service.py": ""}, {"service.py": source}))
    bundle = ContextEngine(graph, sources, extracted).build(changes)
    assert any(
        block.symbol == "CartLine" and "amount: int" in block.code for block in bundle.blocks
    )
    assert all(secret not in block.code for block in bundle.blocks)
    assert bundle.redactions > 0

    limited = ContextEngine(graph, sources, extracted, max_chars=140).build(changes)
    assert limited.truncated and limited.dropped
    assert not any(block.kind == "dependency" for block in limited.blocks)
    assert imported_data_nodes(graph, extracted, "service.py", limit=0) == []
    assert imported_data_nodes(graph, extracted, "missing.py") == []


def test_data_import_limit_is_bounded_and_unknown_wildcards_are_not_guessed() -> None:
    sources = {
        "service.py": "from models import A, B\nfrom unknown import C\nfrom other import *\n",
        "models.py": "class A: pass\nclass B: pass\nclass Hidden: pass\n",
        "other.py": "class Unnamed: pass\n",
    }
    extracted = default_registry().analyze(sources)
    graph = build_graph(extracted).graph
    assert [node.name for node in imported_data_nodes(graph, extracted, "service.py")] == ["A", "B"]
    assert len(imported_data_nodes(graph, extracted, "service.py", limit=1)) == 1
