"""The review orchestrator: runs the pipeline stage by stage.

    parse diff -> filter & redact -> code graph -> context -> static analysis
      -> AI review -> verification -> dedup / prioritize / summarize

It depends on ports (``AIProvider``, a static-analysis runner, verifiers, a progress
reporter) and on the pure analysis modules; it never imports a vendor SDK, a web
framework or a database. A failing stage degrades the review to ``PARTIAL`` instead of
failing it, so a flaky AI provider still yields the deterministic results.
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
from sentinel.analysis.diff.parser import render_file_diff
from sentinel.analysis.diff.secrets import redact_text
from sentinel.analysis.graph.builder import GraphBuildResult, build_graph
from sentinel.analysis.graph.context import ContextBundle, ContextEngine
from sentinel.core.configuration.config import RepoConfig
from sentinel.core.domain.ai import ReviewRequest, StaticHint
from sentinel.core.domain.code import FileSymbols
from sentinel.core.domain.graph import CodeGraph, NodeKind
from sentinel.core.domain.models import (
    AnalysisRun,
    ChangeSet,
    ChangeType,
    Finding,
    Language,
    ReviewResult,
    ReviewStatus,
    StageName,
    StageRecord,
    StageStatus,
    utcnow,
)
from sentinel.core.domain.ports import AIError, AIProvider, NullProgress, ProgressReporter
from sentinel.core.findings.dedup import deduplicate, fingerprint
from sentinel.core.findings.normalize import derive_tags, normalize_ai_findings
from sentinel.core.findings.prioritize import select
from sentinel.core.review.summary import build_summary
from sentinel.core.review.workspace import collect_sources
from sentinel.core.verification.engine import (
    VerificationContext,
    VerificationEngine,
    apply_verification,
)

MAX_DIFF_CHARS = 120_000
MAX_SNAPSHOT_BYTES = 3_000_000
FALLBACK_MARK = "regex fallback"
log = logging.getLogger("sentinel.review")


class SymbolExtractor(Protocol):
    def analyze(self, files: dict[str, str]) -> dict[str, FileSymbols]: ...

    def supports(self, path: str) -> bool: ...


class StaticRunner(Protocol):
    def run(self, workspace: Path, files: list[str]) -> tuple[list[Finding], list[AnalysisRun]]: ...


class StageFailed(Exception):
    pass


class ReviewOrchestrator:
    def __init__(
        self,
        *,
        extractor: SymbolExtractor,
        static_runner: StaticRunner,
        verifier: VerificationEngine,
        ai: AIProvider | None = None,
        config: RepoConfig | None = None,
        progress: ProgressReporter | None = None,
        supported_extensions: Sequence[str] = (
            ".py",
            ".pyi",
            ".ts",
            ".tsx",
            ".mts",
            ".cts",
            ".js",
            ".jsx",
            ".mjs",
            ".cjs",
        ),
        max_graph_files: int = 2_000,
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

    # ------------------------------------------------------------------ stage tracking
    @contextmanager
    def _stage(self, result: ReviewResult, name: StageName) -> Iterator[StageRecord]:
        record = next(s for s in result.stages if s.name is name)
        record.status = StageStatus.RUNNING
        record.started_at = utcnow()
        self.progress.stage_changed(record)
        start = self.clock()
        try:
            yield record
        except StageFailed as exc:
            record.status = StageStatus.FAILED
            record.detail = str(exc)
            result.errors.append(f"{name.value}: {exc}")
        except Exception as exc:  # unexpected bug in a stage: degrade, don't crash
            log.exception("stage %s crashed", name.value)
            record.status = StageStatus.FAILED
            record.detail = f"internal error: {type(exc).__name__}: {exc}"
            result.errors.append(f"{name.value}: internal error: {exc}")
        else:
            if record.status is StageStatus.RUNNING:
                record.status = StageStatus.DONE
        finally:
            record.duration_ms = int((self.clock() - start) * 1000)
            self.progress.stage_changed(record)

    # ------------------------------------------------------------------ pipeline
    def review(
        self,
        changeset: ChangeSet,
        workspace: Path,
        *,
        repository: str = "local",
        review_id: str | None = None,
    ) -> ReviewResult:
        started = self.clock()
        result = ReviewResult(changeset=changeset, status=ReviewStatus.RUNNING)
        if review_id:
            result.review_id = review_id
        result.stages = [StageRecord(name=n) for n in StageName]
        result.provider = self.ai.name if self.ai else None
        result.model = self.ai.model if self.ai else None
        limitations: list[str] = []

        with self._stage(result, StageName.PARSE_DIFF) as st:
            st.metrics = {
                "files": len(changeset.files),
                "hunks": sum(len(f.hunks) for f in changeset.files),
                "added": changeset.lines_added,
                "removed": changeset.lines_removed,
            }
            added, removed = changeset.lines_added, changeset.lines_removed
            st.detail = f"{len(changeset.files)} file(s), +{added}/-{removed}"

        with self._stage(result, StageName.FILTER_FILES) as st:
            outcome = filter_changeset(
                changeset, ignore=self.config.ignore, languages=self.config.languages
            )
            changeset = outcome.changeset
            result.changeset = changeset
            filter_findings = outcome.findings + scan_for_injection(changeset)
            st.metrics = {
                "kept": len(changeset.files),
                "skipped": len(changeset.skipped),
                "redactions": outcome.redactions,
            }
            st.detail = f"kept {len(changeset.files)}, skipped {len(changeset.skipped)}"
            if outcome.redactions:
                st.detail += f", redacted {outcome.redactions} secret(s)"

        reviewable = list(changeset.reviewable())
        changed_paths = [f.path for f in reviewable]

        graph_result: GraphBuildResult | None = None
        sources: dict[str, str] = {}
        with self._stage(result, StageName.BUILD_GRAPH) as st:
            snapshot = collect_sources(
                workspace,
                self.supported_extensions,
                changed_paths,
                max_files=self.max_graph_files,
            )
            sources = snapshot.sources
            symbols = self.extractor.analyze(sources)
            graph_result = build_graph(symbols)
            fallback = sorted(
                p for p, fs in symbols.items() if fs.parse_error and FALLBACK_MARK in fs.parse_error
            )
            parse_errors = sorted(
                p
                for p, fs in symbols.items()
                if fs.parse_error and FALLBACK_MARK not in fs.parse_error
            )
            st.metrics = {
                "files": len(symbols),
                "nodes": len(graph_result.graph),
                "edges": len(graph_result.graph.edges),
                "resolved_calls": graph_result.resolved_calls,
                "unresolved_calls": graph_result.unresolved_calls,
                "loc": sum(fs.loc for fs in symbols.values()),
            }
            st.detail = (
                f"{len(symbols)} files, {len(graph_result.graph)} nodes, "
                f"{len(graph_result.graph.edges)} edges"
            )
            if snapshot.truncated:
                limitations.append(
                    f"Code graph limited to {len(sources)} files (repository is larger)"
                )
            if fallback:
                limitations.append(
                    f"{len(fallback)} JS/TS file(s) parsed with the regex fallback "
                    "(install Node.js + typescript for full structure)"
                )
            if parse_errors:
                limitations.append("Could not parse: " + ", ".join(parse_errors[:5]))

        graph = graph_result.graph if graph_result else CodeGraph()
        file_symbols = graph_result.files if graph_result else {}

        bundle: ContextBundle | None = None
        with self._stage(result, StageName.EXTRACT_CONTEXT) as st:
            engine = ContextEngine(
                graph, sources, file_symbols, max_chars=self.config.review.max_context_chars
            )
            bundle = engine.build(changeset)
            st.metrics = dict(bundle.stats.items())
            st.detail = (
                f"{bundle.stats.get('changed_symbols', 0)} changed symbol(s), "
                f"{len(bundle.blocks)} context block(s)"
            )
            if bundle.truncated:
                limitations.append(
                    f"Context budget reached; {len(bundle.dropped)} lower-priority block(s) "
                    "omitted from the AI prompt"
                )

        static_findings: list[Finding] = []
        with self._stage(result, StageName.STATIC_ANALYSIS) as st:
            targets = [
                p
                for p in changed_paths
                if posixpath.splitext(p)[1].lower() in self.supported_extensions
            ]
            found, runs = self.static_runner.run(workspace, targets)
            result.analysis_runs = runs
            changed_set = set(changed_paths)
            static_findings = [f for f in found if f.file in changed_set]
            st.metrics = {
                "findings": len(static_findings),
                "tools_ok": sum(1 for r in runs if r.status == "ok"),
                "tools_unavailable": sum(1 for r in runs if r.status == "unavailable"),
            }
            st.detail = ", ".join(f"{r.tool}:{r.status}" for r in runs) or "no analyzers applied"
            if any(r.status in ("failed", "timeout") for r in runs):
                result.errors.append(
                    "static analysis: "
                    + ", ".join(
                        f"{r.tool} {r.status}" for r in runs if r.status in ("failed", "timeout")
                    )
                )

        ai_findings: list[Finding] = []
        with self._stage(result, StageName.AI_REVIEW) as st:
            if self.ai is None:
                st.status = StageStatus.SKIPPED
                st.detail = "no AI provider configured: deterministic review only"
                limitations.append("AI review skipped (no provider configured)")
            elif not reviewable:
                st.status = StageStatus.SKIPPED
                st.detail = "nothing reviewable"
            else:
                request = self._build_request(
                    result.review_id, repository, changeset, bundle, static_findings
                )
                try:
                    ai_result = self.ai.review(request)
                except AIError as exc:
                    raise StageFailed(str(exc)) from exc
                result.usage = result.usage + ai_result.usage
                known = set(sources) | set(changed_paths)
                ai_findings = normalize_ai_findings(
                    ai_result.payload, provider=ai_result.provider, known_files=known
                )
                st.metrics = {
                    "findings": len(ai_findings),
                    "input_tokens": ai_result.usage.input_tokens,
                    "output_tokens": ai_result.usage.output_tokens,
                    "attempts": ai_result.attempts,
                    "cached": int(ai_result.cached),
                }
                st.detail = (
                    f"{len(ai_findings)} candidate finding(s) from {ai_result.provider}/"
                    f"{ai_result.model}" + (" (cached)" if ai_result.cached else "")
                )

        all_static = filter_findings + static_findings
        vctx = VerificationContext(
            graph=graph,
            sources=sources,
            changeset=changeset,
            static_findings=all_static,
            symbols=file_symbols,
        )
        with self._stage(result, StageName.VERIFICATION) as st:
            for f in all_static:
                apply_verification(f, VerificationEngine.deterministic(f, vctx))
            for f in ai_findings:
                apply_verification(f, self.verifier.verify(f, vctx))
            counts: dict[str, int] = {}
            for f in ai_findings:
                key = f.verification.status.value if f.verification else "none"
                counts[key] = counts.get(key, 0) + 1
            st.metrics = dict(counts.items())
            st.detail = (
                ", ".join(f"{v} {k}" for k, v in counts.items())
                if ai_findings
                else f"{len(all_static)} deterministic finding(s)"
            )

        with self._stage(result, StageName.FINALIZE) as st:
            everything = all_static + ai_findings
            from_filter = {id(f) for f in filter_findings}
            for f in everything:
                node = graph.enclosing(f.file, f.line_start)
                f.symbol = node.name if node is not None else None
                if id(f) not in from_filter:
                    change = changeset.get(f.file)
                    f.in_changed_lines = bool(
                        change and change.touches(f.line_start, f.line_end, slack=2)
                    )
                if not f.tags:
                    f.tags = derive_tags(f.title, f.explanation)
                f.fingerprint = fingerprint(f)
            merged = deduplicate(everything)
            surfaced, suppressed = select(merged, changeset, self.config)
            result.findings = surfaced
            result.suppressed = suppressed
            changed_names = [
                c.name
                for c in (bundle.changed_symbols if bundle else [])
                if c.kind is not NodeKind.FILE
            ]
            result.summary = build_summary(
                changeset,
                surfaced,
                suppressed,
                changed_symbols=changed_names,
                runs=result.analysis_runs,
                limitations=limitations,
            )
            if bundle is not None:
                result.graph = bundle.subgraph.to_dict()
            result.sources = self._snapshot(changeset, sources, bundle, surfaced)
            st.detail = f"{len(surfaced)} surfaced, {len(suppressed)} suppressed"
            st.metrics = {
                "surfaced": len(surfaced),
                "suppressed": len(suppressed),
                "merged": len(everything) - len(merged),
            }

        failed = [s for s in result.stages if s.status is StageStatus.FAILED]
        result.status = ReviewStatus.PARTIAL if failed or result.errors else ReviewStatus.COMPLETED
        if failed and all(s.name is StageName.FINALIZE for s in failed):
            result.status = ReviewStatus.FAILED
        result.duration_ms = int((self.clock() - started) * 1000)
        return result

    # ------------------------------------------------------------------ helpers
    def _build_request(
        self,
        review_id: str,
        repository: str,
        changeset: ChangeSet,
        bundle: ContextBundle | None,
        static_findings: list[Finding],
    ) -> ReviewRequest:
        diffs: list[str] = []
        used = 0
        for change in changeset.reviewable():
            text = render_file_diff(change)
            if used + len(text) > MAX_DIFF_CHARS:
                diffs.append(f"--- {change.path}: diff omitted (size budget reached)")
                continue
            used += len(text)
            diffs.append(text)
        for change in changeset.files:
            if change.change_type is ChangeType.DELETED:
                diffs.append(f"--- a/{change.path}\n+++ /dev/null\n(file deleted)")
        languages = sorted(
            {f.language.value for f in changeset.files if f.language is not Language.OTHER}
        )
        return ReviewRequest(
            review_id=review_id,
            repository=repository,
            title=changeset.title,
            diff="\n".join(diffs),
            changed_files=[f.path for f in changeset.files],
            context=bundle.blocks if bundle else [],
            static_findings=[
                StaticHint(
                    tool=(f.origins[0].split(":")[0] if f.origins else "static"),
                    rule=f.rule_id,
                    file=f.file,
                    line=f.line_start,
                    message=f.title,
                )
                for f in static_findings[:40]
            ],
            categories=self.config.review.enabled_categories(),
            max_findings=max(self.config.review.max_findings, 10),
            languages=languages,
        )

    @staticmethod
    def _snapshot(
        changeset: ChangeSet,
        sources: dict[str, str],
        bundle: ContextBundle | None,
        findings: list[Finding],
    ) -> dict[str, str]:
        """Redacted copies of the files the UI may need to show (diff, context, graph)."""
        wanted: list[str] = [f.path for f in changeset.reviewable()]
        wanted += [f.file for f in findings]
        if bundle is not None:
            wanted += [b.file for b in bundle.blocks]
            wanted += [n.file for n in bundle.subgraph.nodes if n.file]
        out: dict[str, str] = {}
        total = 0
        for path in dict.fromkeys(wanted):
            text = sources.get(path)
            if text is None or total + len(text) > MAX_SNAPSHOT_BYTES:
                continue
            red, _ = redact_text(text)
            out[path] = red
            total += len(red)
        return out
