"""Trusted runtime parsers cover TS without a project install or silent partial success."""

import shutil
from pathlib import Path

import pytest

from sentinel.analysis.static import js_tools
from sentinel.analysis.static.base import ToolResult
from sentinel.analysis.static.js_tools import ESLintAnalyzer
from sentinel.core.domain.models import ToolStatus


@pytest.mark.skipif(
    shutil.which("eslint") is None or js_tools._trusted_ts_parser() is None,
    reason="trusted ESLint and TypeScript parser required",
)
def test_installed_runtime_lints_real_typescript_without_project_modules(tmp_path: Path) -> None:
    (tmp_path / "unsafe.ts").write_text(
        "export function unsafe(value: string): unknown { return eval(value); }\n"
    )
    result = ESLintAnalyzer(trust_workspace=False).run(tmp_path, ["unsafe.ts"])
    assert result.run.status == ToolStatus.OK, result.run
    assert [(f.file, f.rule_id) for f in result.findings] == [("unsafe.ts", "eslint/no-eval")]


@pytest.mark.parametrize("trusted", [True, False])
def test_installed_parser_is_used_without_project_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, trusted: bool
) -> None:
    installed = tmp_path / "installed-parser"
    configs = []
    monkeypatch.setattr(js_tools, "_trusted_ts_parser", lambda: installed)
    monkeypatch.setattr(js_tools, "find_tool", lambda *args: "/trusted/eslint")

    def run(cmd, *args):
        configs.append(Path(cmd[cmd.index("--config") + 1]).read_text())
        return ToolResult(0, "[]", "", 1)

    monkeypatch.setattr(js_tools, "run_tool", run)
    result = ESLintAnalyzer(trust_workspace=trusted).run(tmp_path, ["app.ts"])
    assert result.run.status == ToolStatus.OK and not result.run.detail
    assert installed.as_posix() in configs[0]


def test_missing_parser_with_mixed_files_is_not_complete_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(js_tools, "_trusted_ts_parser", lambda: None)
    monkeypatch.setattr(js_tools, "find_tool", lambda *args: "/trusted/eslint")
    monkeypatch.setattr(js_tools, "run_tool", lambda *args: ToolResult(0, "[]", "", 1))
    result = ESLintAnalyzer(trust_workspace=False).run(tmp_path, ["app.ts", "app.js"])
    assert result.run.status == ToolStatus.UNAVAILABLE
    assert "TypeScript files skipped" in result.run.detail
    javascript = ESLintAnalyzer(trust_workspace=False).run(tmp_path, ["app.js"])
    assert javascript.run.status == ToolStatus.OK and not javascript.run.detail


def test_untrusted_repository_parser_is_never_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "node_modules/@typescript-eslint/parser").mkdir(parents=True)
    monkeypatch.setattr(js_tools, "_trusted_ts_parser", lambda: None)
    monkeypatch.setattr(js_tools, "find_tool", lambda *args: "/trusted/eslint")
    result = ESLintAnalyzer(trust_workspace=False).run(tmp_path, ["app.ts"])
    assert result.run.status == ToolStatus.UNAVAILABLE
