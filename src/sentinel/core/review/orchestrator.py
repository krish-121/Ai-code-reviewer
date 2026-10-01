"""The review orchestrator: runs the pipeline stage by stage.

    parse diff -> filter & redact -> code graph -> context -> static analysis
      -> AI review -> verification -> dedup / prioritize / summarize

Called by ``services/reviews.py`` (which the CLI, API worker and GitHub flow all use).
Each stage is one method below; stages share their intermediate results through a
``PipelineState``. The orchestrator depends only on ports (``AIProvider``, a static
runner, a verifier, a progress reporter) and on pure analysis modules: never on a vendor
SDK, a web framework or a database.

A failing stage degrades the review to ``PARTIAL`` instead of failing it, so a flaky AI
provider still yields the deterministic results.
"""

from __future__ import annotations

import logging
import posixpath
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from sentinel.analysis.diff.filtering import filter_changeset
from sentinel.analysis.diff.injection import scan_for_injection
from sentinel.analysis.graph.builder import build_graph
from sentinel.analysis.graph.context import ContextEngine
from sentinel.core.configuration.config import RepoConfig
from sentinel.core.domain.code import FileSymbols
from sentinel.core.domain.errors import SentinelError
from sentinel.core.domain.graph import NodeKind
from sentinel.core.domain.models import (
    TOOL_PROBLEMS,
    AnalysisRun,
    ChangeSet,
    Finding,
    ReviewResult,
    ReviewStatus,
    StageName,
    StageRecord,
    StageStatus,
    ToolStatus,
    utcnow,
)
from sentinel.core.domain.ports import AIError, AIProvider, NullProgress, ProgressReporter
from sentinel.core.findings.dedup import deduplicate, fingerprint
from sentinel.core.findings.normalize import derive_tags, normalize_ai_findings
from sentinel.core.findings.prioritize import select
from sentinel.core.review.ai_request import build_review_request
from sentinel.core.review.state import PipelineState
from sentinel.core.review.summary import build_summary
from sentinel.core.review.workspace import collect_sources, snapshot_sources
from sentinel.core.verification.engine import (
    VerificationContext,
    VerificationEngine,
    apply_verification,
)

SOURCE_EXTENSIONS = (".py", ".pyi", ".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
DEFAULT_MAX_GRAPH_FILES = 2_000
MAX_PARSE_ERRORS_LISTED = 5
# A finding counts as "on a changed line" if it is within this many lines of one.
CHANGED_LINE_SLACK = 2
log = logging.getLogger("sentinel.review")


class SymbolExtractor(Protocol):
    """Turns source files into ``FileSymbols`` (implemented by ``analysis.ast.registry``)."""

    def analyze(self, files: dict[str, str]) -> dict[str, FileSymbols]:
        """Analyze every file in ``files`` (path -> source)."""

    def supports(self, path: str) -> bool:
        """True when some language analyzer handles this path."""


class StaticRunner(Protocol):
    """Runs all static analyzers (implemented by ``analysis.static.runner``)."""

    def run(self, workspace: Path, files: list[str]) -> tuple[list[Finding], list[AnalysisRun]]:
        """Analyze ``files`` and return findings plus one run record per tool."""


class StageFailedError(SentinelError):
    """Raised inside a stage to mark it failed with a readable reason."""


class ReviewOrchestrator:
    """Runs one review from a parsed diff to a finished ``ReviewResult``."""

    def __init__(
        self,
        *,
        extractor: SymbolExtractor,
        static_runner: StaticRunner,
        verifier: VerificationEngine,
        ai: AIProvider | None = None,
        config: RepoConfig | None = None,
        progress: ProgressReporter | None = None,
        supported_extensions: Sequence[str] = SOURCE_EXTENSIONS,
        max_graph_files: int = DEFAULT_MAX_GRAPH_FILES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.extractor = extractor
        self.static_runner = static_runner
        self.verifier = verifier
        self.ai = ai
        self.config = config or RepoConfig()
        self.progress = progress or NullProgress()
        self.supported_extensions = set(supported_extensions)
        self.max_graph_files = max_graph_files
        self.clock = clock

    def review(
        self,
        changeset: ChangeSet,
        workspace: Path,
        *,
        repository: str = "local",
        review_id: str | None = None,
    ) -> ReviewResult:
        """Run every stage in order and return the result (never raises for stage errors)."""
        started = self.clock()
        state = PipelineState(
            result=self._new_result(changeset, review_id),
            workspace=workspace,
            repository=repository,
        )
        stages: list[tuple[StageName, Callable[[PipelineState, StageRecord], None]]] = [
            (StageName.PARSE_DIFF, self._parse_diff),
            (StageName.FILTER_FILES, self._filter_files),
            (StageName.BUILD_GRAPH, self._build_graph),
            (StageName.EXTRACT_CONTEXT, self._extract_context),
            (StageName.STATIC_ANALYSIS, self._static_analysis),
            (StageName.AI_REVIEW, self._ai_review),
            (StageName.VERIFICATION, self._verify),
            (StageName.FINALIZE, self._finalize),
        ]
        for name, run_stage in stages:
            with self._stage(state.result, name) as record:
                run_stage(state, record)
        state.result.status = _final_status(state.result)
        state.result.duration_ms = int((self.clock() - started) * 1000)
        return state.result

    # ------------------------------------------------------------------ stages
    def _parse_diff(self, state: PipelineState, record: StageRecord) -> None:
        """Record what the diff contains (it was parsed before the review started)."""
        changeset = state.changeset
        added, removed = changeset.lines_added, changeset.lines_removed
        record.metrics = {
            "files": len(changeset.files),
            "hunks": sum(len(f.hunks) for f in changeset.files),
            "added": added,
            "removed": removed,
        }
        record.detail = f"{len(changeset.files)} file(s), +{added}/-{removed}"

    def _filter_files(self, state: PipelineState, record: StageRecord) -> None:
        """Drop binary/generated/sensitive files, redact secrets, flag prompt injection."""
        outcome = filter_changeset(
            state.changeset, ignore=self.config.ignore, languages=self.config.languages
        )
        state.result.changeset = outcome.changeset
        state.filter_findings = outcome.findings + scan_for_injection(outcome.changeset)
        kept, skipped = len(outcome.changeset.files), len(outcome.changeset.skipped)
        record.metrics = {"kept": kept, "skipped": skipped, "redactions": outcome.redactions}
        record.detail = f"kept {kept}, skipped {skipped}"
        if outcome.redactions:
            record.detail += f", redacted {outcome.redactions} secret(s)"

    def _build_graph(self, state: PipelineState, record: StageRecord) -> None:
        """Read the repository's code files and build the code graph from them."""
        snapshot = collect_sources(
            state.workspace,
            self.supported_extensions,
            state.changed_paths,
            max_files=self.max_graph_files,
        )
        state.sources = snapshot.sources
        symbols = self.extractor.analyze(state.sources)
        built = build_graph(symbols)
        state.graph, state.file_symbols = built.graph, built.files
        record.metrics = {
            "files": len(symbols),
            "nodes": len(built.graph),
            "edges": len(built.graph.edges),
            "resolved_calls": built.resolved_calls,
            "unresolved_calls": built.unresolved_calls,
            "loc": sum(fs.loc for fs in symbols.values()),
        }
        record.detail = (
            f"{len(symbols)} files, {len(built.graph)} nodes, {len(built.graph.edges)} edges"
        )
        if snapshot.truncated:
            state.limitations.append(
                f"Code graph limited to {len(state.sources)} files (repository is larger)"
            )
        state.limitations += _parse_limitations(symbols)

    def _extract_context(self, state: PipelineState, record: StageRecord) -> None:
        """Choose the code around the change that the AI reviewer should see."""
        engine = ContextEngine(
            state.graph,
            state.sources,
            state.file_symbols,
            max_chars=self.config.review.max_context_chars,
        )
        bundle = engine.build(state.changeset)
        state.bundle = bundle
        record.metrics = dict(bundle.stats.items())
        record.detail = (
            f"{bundle.stats.get('changed_symbols', 0)} changed symbol(s), "
            f"{len(bundle.blocks)} context block(s)"
        )
        if bundle.truncated:
            state.limitations.append(
                f"Context budget reached; {len(bundle.dropped)} lower-priority block(s) "
                "omitted from the AI prompt"
            )

    def _static_analysis(self, state: PipelineState, record: StageRecord) -> None:
        """Run the static analyzers on the changed files and keep their findings."""
        targets = [
            p
            for p in state.changed_paths
            if posixpath.splitext(p)[1].lower() in self.supported_extensions
        ]
        found, runs = self.static_runner.run(state.workspace, targets)
        state.result.analysis_runs = runs
        changed = set(state.changed_paths)
        state.static_findings = [f for f in found if f.file in changed]
        record.metrics = {
            "findings": len(state.static_findings),
            "tools_ok": sum(1 for r in runs if r.status == ToolStatus.OK),
            "tools_unavailable": sum(1 for r in runs if r.status == ToolStatus.UNAVAILABLE),
        }
        record.detail = ", ".join(f"{r.tool}:{r.status}" for r in runs) or "no analyzers applied"
        problems = [f"{r.tool} {r.status}" for r in runs if r.status in TOOL_PROBLEMS]
        if problems:
            state.result.errors.append("static analysis: " + ", ".join(problems))

    def _ai_review(self, state: PipelineState, record: StageRecord) -> None:
        """Ask the AI provider for candidate findings (skipped without a provider)."""
        if self.ai is None:
            record.status = StageStatus.SKIPPED
            record.detail = "no AI provider configured: deterministic review only"
            state.limitations.append("AI review skipped (no provider configured)")
            return
        if not state.changed_paths:
            record.status = StageStatus.SKIPPED
            record.detail = "nothing reviewable"
            return
        request = build_review_request(
            review_id=state.result.review_id,
            repository=state.repository,
            changeset=state.changeset,
            bundle=state.bundle,
            static_findings=state.static_findings,
            config=self.config,
        )
        try:
            answer = self.ai.review(request)
        except AIError as exc:
            raise StageFailedError(str(exc)) from exc
        state.result.usage = state.result.usage + answer.usage
        known_files = set(state.sources) | set(state.changed_paths)
        state.ai_findings = normalize_ai_findings(
            answer.payload, provider=answer.provider, known_files=known_files
        )
        record.metrics = {
            "findings": len(state.ai_findings),
            "input_tokens": answer.usage.input_tokens,
            "output_tokens": answer.usage.output_tokens,
            "attempts": answer.attempts,
            "cached": int(answer.cached),
        }
        cached = " (cached)" if answer.cached else ""
        record.detail = (
            f"{len(state.ai_findings)} candidate finding(s) "
            f"from {answer.provider}/{answer.model}{cached}"
        )

    def _verify(self, state: PipelineState, record: StageRecord) -> None:
        """Check every AI claim against the code; deterministic findings verify by construction."""
        context = VerificationContext(
            graph=state.graph,
            sources=state.sources,
            changeset=state.changeset,
            static_findings=state.deterministic_findings,
            symbols=state.file_symbols,
        )
        for finding in state.deterministic_findings:
            apply_verification(finding, VerificationEngine.deterministic(finding, context))
        counts: dict[str, int] = {}
        for finding in state.ai_findings:
            apply_verification(finding, self.verifier.verify(finding, context))
            status = finding.verification.status.value if finding.verification else "none"
            counts[status] = counts.get(status, 0) + 1
        record.metrics = dict(counts.items())
        if state.ai_findings:
            record.detail = ", ".join(f"{n} {status}" for status, n in counts.items())
        else:
            record.detail = f"{len(state.deterministic_findings)} deterministic finding(s)"

    def _finalize(self, state: PipelineState, record: StageRecord) -> None:
        """Merge duplicates, rank, pick what to show, summarize, and snapshot sources."""
        everything = state.deterministic_findings + state.ai_findings
        self._annotate(state, everything)
        merged = deduplicate(everything)
        surfaced, suppressed = select(merged, state.changeset, self.config)
        result = state.result
        result.findings, result.suppressed = surfaced, suppressed
        changed_names = [
            c.name
            for c in (state.bundle.changed_symbols if state.bundle else [])
            if c.kind is not NodeKind.FILE
        ]
        result.summary = build_summary(
            state.changeset,
            surfaced,
            suppressed,
            changed_symbols=changed_names,
            runs=result.analysis_runs,
            limitations=state.limitations,
        )
        if state.bundle is not None:
            result.graph = state.bundle.subgraph.to_dict()
        result.sources = snapshot_sources(state.changeset, state.sources, state.bundle, surfaced)
        record.detail = f"{len(surfaced)} surfaced, {len(suppressed)} suppressed"
        record.metrics = {
            "surfaced": len(surfaced),
            "suppressed": len(suppressed),
            "merged": len(everything) - len(merged),
        }

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _annotate(state: PipelineState, findings: list[Finding]) -> None:
        """Fill in symbol, changed-line flag, tags and fingerprint before deduplication."""
        from_filter = {id(f) for f in state.filter_findings}
        for finding in findings:
            node = state.graph.enclosing(finding.file, finding.line_start)
            finding.symbol = node.name if node is not None else None
            # Filter findings (secrets, sensitive files) are about the change by definition.
            if id(finding) not in from_filter:
                change = state.changeset.get(finding.file)
                finding.in_changed_lines = bool(
                    change
                    and change.touches(
                        finding.line_start, finding.line_end, slack=CHANGED_LINE_SLACK
                    )
                )
            if not finding.tags:
                finding.tags = derive_tags(finding.title, finding.explanation)
            finding.fingerprint = fingerprint(finding)

    def _new_result(self, changeset: ChangeSet, review_id: str | None) -> ReviewResult:
        result = ReviewResult(changeset=changeset, status=ReviewStatus.RUNNING)
        if review_id:
            result.review_id = review_id
        result.stages = [StageRecord(name=name) for name in StageName]
        result.provider = self.ai.name if self.ai else None
        result.model = self.ai.model if self.ai else None
        return result

    @contextmanager
    def _stage(self, result: ReviewResult, name: StageName) -> Iterator[StageRecord]:
        """Time a stage, report its progress, and turn any exception into a failed stage."""
        record = next(s for s in result.stages if s.name is name)
        record.status = StageStatus.RUNNING
        record.started_at = utcnow()
        self.progress.stage_changed(record)
        start = self.clock()
        try:
            yield record
        except SentinelError as exc:
            _mark_failed(result, record, str(exc))
        except Exception as exc:  # unexpected bug in a stage: degrade, don't crash
            log.exception("stage %s crashed", name.value)
            _mark_failed(result, record, f"internal error: {type(exc).__name__}: {exc}")
        else:
            if record.status is StageStatus.RUNNING:
                record.status = StageStatus.DONE
        finally:
            record.duration_ms = int((self.clock() - start) * 1000)
            self.progress.stage_changed(record)


def _mark_failed(result: ReviewResult, record: StageRecord, reason: str) -> None:
    record.status = StageStatus.FAILED
    record.detail = reason
    result.errors.append(f"{record.name.value}: {reason}")


def _final_status(result: ReviewResult) -> ReviewStatus:
    """COMPLETED, PARTIAL (something failed but findings exist) or FAILED (finalize failed)."""
    failed = [s for s in result.stages if s.status is StageStatus.FAILED]
    if failed and all(s.name is StageName.FINALIZE for s in failed):
        return ReviewStatus.FAILED
    if failed or result.errors:
        return ReviewStatus.PARTIAL
    return ReviewStatus.COMPLETED


def _parse_limitations(symbols: dict[str, FileSymbols]) -> list[str]:
    """Human-readable notes about files that could not be parsed fully."""
    notes: list[str] = []
    fallback = sorted(p for p, fs in symbols.items() if fs.used_regex_fallback)
    broken = sorted(p for p, fs in symbols.items() if fs.failed_to_parse)
    if fallback:
        notes.append(
            f"{len(fallback)} JS/TS file(s) parsed with the regex fallback "
            "(install Node.js + typescript for full structure)"
        )
    if broken:
        notes.append("Could not parse: " + ", ".join(broken[:MAX_PARSE_ERRORS_LISTED]))
    return notes
