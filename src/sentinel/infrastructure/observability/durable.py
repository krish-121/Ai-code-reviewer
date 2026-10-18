"""Export persisted worker results across processes without retaining sample history."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from sentinel.infrastructure.database.models import AnalysisRunRow, Finding, FixAttempt, Review
from sentinel.infrastructure.observability.metrics import Metrics


def render_persisted(session: Session) -> str:
    """Metrics over retained history; the database is the shared source of truth."""
    metrics = Metrics()
    reviews = select(
        Review.status,
        Review.duration_ms,
        Review.input_tokens,
        Review.output_tokens,
        Review.stages,
        Review.summary,
    ).where(Review.finished_at.is_not(None))
    for status, duration, inputs, outputs, stages, summary in session.execute(reviews).yield_per(
        100
    ):
        metrics.inc("sentinel_reviews_total", status=status)
        metrics.observe("sentinel_review_duration_ms", duration or 0)
        metrics.inc("sentinel_ai_tokens_total", inputs, direction="input")
        metrics.inc("sentinel_ai_tokens_total", outputs, direction="output")
        metrics.inc(
            "sentinel_files_analyzed_total",
            (summary or {}).get("stats", {}).get("files_reviewed", 0),
        )
        for stage in stages or []:
            if stage.get("duration_ms") is not None:
                metrics.observe(
                    "sentinel_stage_duration_ms", stage["duration_ms"], stage=stage["name"]
                )
    for source, status in session.execute(
        select(Finding.source, Finding.verification_status)
    ).yield_per(100):
        metrics.inc("sentinel_findings_total", source=source, verification=status or "none")
    _fix_metrics(session, metrics)
    for tool, status in session.execute(
        select(AnalysisRunRow.tool, AnalysisRunRow.status)
    ).yield_per(100):
        metrics.inc("sentinel_analysis_runs_total", tool=tool, status=status)
    return metrics.render()


def _fix_metrics(session: Session, metrics: Metrics) -> None:
    rows = select(
        FixAttempt.status, FixAttempt.created_at, FixAttempt.finished_at, FixAttempt.checks
    ).where(FixAttempt.finished_at.is_not(None))
    for status, start, end, checks in session.execute(rows).yield_per(100):
        metrics.record_fix(
            status, (end - start).total_seconds() * 1000, ((c["name"], c["status"]) for c in checks)
        )
