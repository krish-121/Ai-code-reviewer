"""Terminal rendering with rich."""

from __future__ import annotations

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from sentinel.core.domain.models import (
    STAGE_LABELS,
    Finding,
    ReviewResult,
    RiskLevel,
    Severity,
    StageName,
    StageRecord,
    StageStatus,
    VerificationStatus,
)

SEV_STYLE = {Severity.HIGH: "bold red", Severity.MEDIUM: "bold dark_orange", Severity.LOW: "yellow"}
SEV_DOT = {Severity.HIGH: "🔴", Severity.MEDIUM: "🟠", Severity.LOW: "🟡"}
RISK_STYLE = {
    RiskLevel.HIGH: "bold white on red",
    RiskLevel.MEDIUM: "bold black on dark_orange",
    RiskLevel.LOW: "black on yellow",
    RiskLevel.NONE: "bold white on green",
}
VER_STYLE = {
    VerificationStatus.SUPPORTED: "green",
    VerificationStatus.LIKELY: "cyan",
    VerificationStatus.UNCERTAIN: "yellow",
    VerificationStatus.REJECTED: "red",
}
STAGE_MARK = {
    StageStatus.PENDING: ("○", "dim"),
    StageStatus.RUNNING: ("●", "bold cyan"),
    StageStatus.DONE: ("✓", "green"),
    StageStatus.SKIPPED: ("–", "dim"),
    StageStatus.FAILED: ("✗", "bold red"),
}


class LiveProgress:
    """ProgressReporter that redraws the stage list as the pipeline advances."""

    def __init__(self, console: Console) -> None:
        self.console = console
        self.stages: dict[StageName, StageRecord] = {n: StageRecord(name=n) for n in StageName}
        self.live = Live(self._render(), console=console, refresh_per_second=8, transient=False)

    def __enter__(self) -> LiveProgress:
        if self.console.is_terminal:
            self.live.__enter__()
        return self

    def __exit__(self, *exc: object) -> None:
        if self.console.is_terminal:
            self.live.update(self._render())
            self.live.__exit__(None, None, None)

    def stage_changed(self, stage: StageRecord) -> None:
        self.stages[stage.name] = stage.model_copy()
        if self.console.is_terminal:
            self.live.update(self._render())
        elif stage.status is not StageStatus.RUNNING:
            mark, _ = STAGE_MARK[stage.status]
            self.console.print(f"{mark} {STAGE_LABELS[stage.name]} {stage.detail}", highlight=False)

    def _render(self) -> Table:
        table = Table.grid(padding=(0, 1))
        table.add_row(Text("Analyzing…", style="bold"))
        for name in StageName:
            st = self.stages[name]
            mark, style = STAGE_MARK[st.status]
            timing = (
                f"{st.duration_ms} ms"
                if st.duration_ms is not None
                and st.status in (StageStatus.DONE, StageStatus.FAILED)
                else ""
            )
            table.add_row(
                Text(f"{mark} {STAGE_LABELS[name]}", style=style),
                Text(timing, style="dim"),
                Text(st.detail[:90], style="dim"),
            )
        return table


def render_summary(console: Console, result: ReviewResult) -> None:
    s = result.summary
    st = s.stats
    grid = Table.grid(padding=(0, 3))
    grid.add_column(justify="left")
    grid.add_column(justify="left")
    left = Table.grid(padding=(0, 2))
    left.add_row("Files changed", str(st.files_changed))
    left.add_row("Files reviewed", str(st.files_reviewed))
    left.add_row("Lines added", f"[green]+{st.lines_added}[/]")
    left.add_row("Lines removed", f"[red]-{st.lines_removed}[/]")
    right = Table.grid(padding=(0, 2))
    for sev in Severity:
        right.add_row(
            f"{SEV_DOT[sev]} {sev.value.capitalize()}", str(st.by_severity.get(sev.value, 0))
        )
    for cat, n in st.by_category.items():
        right.add_row(f"  {cat.capitalize()}", str(n))
    grid.add_row(left, right)
    risk = Text(f" RISK: {s.risk.value.upper()} ", style=RISK_STYLE[s.risk])
    sections: list[RenderableType] = [risk, Text(""), grid]
    for title, items in (
        ("What changed", s.what_changed),
        ("What deserves attention", s.attention),
        ("What was verified", s.verified),
        ("What remains uncertain", s.uncertain),
    ):
        if items:
            sections.append(Text(f"\n{title}", style="bold"))
            sections.extend(Text(f"  • {item}") for item in items)
    meta = f"{result.review_id} · {result.status.value} · {result.duration_ms} ms"
    if result.provider:
        meta += (
            f" · {result.provider}/{result.model} · {result.usage.input_tokens}+"
            f"{result.usage.output_tokens} tokens"
        )
    console.print(
        Panel(Group(*sections), title="[bold]Review summary[/]", subtitle=meta, border_style="dim")
    )


def _snippet(result: ReviewResult, f: Finding) -> Syntax | None:
    source = result.sources.get(f.file)
    if not source:
        return None
    lexer = Syntax.guess_lexer(f.file, code=source)
    start = max(1, f.line_start - 2)
    end = f.line_end + 2
    return Syntax(
        source,
        lexer,
        line_numbers=True,
        line_range=(start, end),
        highlight_lines=set(range(f.line_start, f.line_end + 1)),
        word_wrap=True,
        theme="ansi_dark",
    )


def render_finding(console: Console, result: ReviewResult, f: Finding, *, verbose: bool) -> None:
    ver = f.verification
    head = Text()
    head.append(f"{SEV_DOT[f.severity]} {f.severity.value.upper()}", style=SEV_STYLE[f.severity])
    head.append(f"  {f.title}", style="bold")
    meta = Text(f"{f.location}", style="cyan")
    meta.append(f"   confidence {f.confidence:.0%}", style="dim")
    if ver:
        meta.append("   verification ", style="dim")
        meta.append(ver.status.value.upper(), style=VER_STYLE[ver.status])
    meta.append(f"   {f.category.value} · {f.source.value}", style="dim")
    body: list[RenderableType] = [head, meta, Text("")]
    if f.explanation:
        body.append(Text(f.explanation))
    if ver and ver.call_path:
        body.append(Text("\nReachable from: " + " → ".join(ver.call_path), style="magenta"))
    if verbose and f.evidence:
        body.append(Text("\nEvidence", style="bold"))
        for e in f.evidence[:6]:
            body.append(Text(f"  • [{e.source}] {e.text}"))
    if verbose and ver:
        body.append(Text("\nVerification", style="bold"))
        for c in ver.checks:
            style = {"supports": "green", "contradicts": "red"}.get(c.outcome.value, "dim")
            body.append(Text(f"  {c.outcome.value:<11} {c.name}: {c.detail}", style=style))
    snippet = _snippet(result, f)
    if snippet is not None:
        body.append(Text(""))
        body.append(snippet)
    if f.suggested_fix:
        body.append(Text("\nSuggested fix: ", style="bold").append(f.suggested_fix, style=""))
    console.print(
        Panel(
            Group(*body),
            border_style=SEV_STYLE[f.severity].split()[-1],
            subtitle=f"[dim]{f.id}[/]",
            subtitle_align="right",
        )
    )


def render_review(
    console: Console, result: ReviewResult, *, verbose: bool = False, show_suppressed: bool = False
) -> None:
    render_summary(console, result)
    if not result.findings:
        console.print("[green]No findings to report.[/]")
    for f in result.findings:
        render_finding(console, result, f, verbose=verbose)
    if result.suppressed:
        if show_suppressed:
            table = Table(title="Suppressed findings", show_lines=False, header_style="dim")
            table.add_column("ID", style="dim")
            table.add_column("Finding")
            table.add_column("Location", style="cyan")
            table.add_column("Why", style="dim")
            for f in result.suppressed:
                table.add_row(f.id, escape(f.title), f.location, escape(f.suppressed_reason or ""))
            console.print(table)
        else:
            console.print(
                f"[dim]{len(result.suppressed)} finding(s) suppressed (rejected by verification, "
                "below threshold or pre-existing). Use --show-suppressed to list them.[/]"
            )
    if result.errors:
        console.print(
            Panel("\n".join(escape(e) for e in result.errors), title="Errors", border_style="red")
        )


def findings_table(findings: list[Finding], title: str) -> Table:
    table = Table(title=title, header_style="bold")
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Sev")
    table.add_column("Finding")
    table.add_column("Location", style="cyan")
    table.add_column("Conf", justify="right")
    table.add_column("Verification")
    table.add_column("Status")
    for f in findings:
        ver = f.verification.status if f.verification else None
        table.add_row(
            f.id,
            Text(f.severity.value.upper(), style=SEV_STYLE[f.severity]),
            escape(f.title),
            f.location,
            f"{f.confidence:.0%}",
            Text(ver.value if ver else "-", style=VER_STYLE[ver] if ver else "dim"),
            f.status.value,
        )
    return table
