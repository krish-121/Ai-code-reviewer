"""A tiny in-process metrics registry exposed in Prometheus text format at /metrics.

Deliberately small: counters and histograms with labels, no client library. Enough to
answer "how long do reviews take, how often does verification reject AI claims, how
often do fixes validate?" without building an observability platform.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from sentinel.core.domain.models import ReviewResult, StageStatus

BUCKETS_MS = (50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000, 60000, 120000)
Labels = tuple[tuple[str, str], ...]


@dataclass
class Histogram:
    """Constant-space cumulative buckets, count and sum."""

    count: int = 0
    total: float = 0.0
    buckets: list[int] = field(default_factory=lambda: [0] * len(BUCKETS_MS))

    def observe(self, value: float) -> None:
        """Accumulate without retaining individual samples."""
        self.count += 1
        self.total += value
        for i, bound in enumerate(BUCKETS_MS):
            self.buckets[i] += int(value <= bound)


class Metrics:
    """Thread-safe in-process counters and histograms, exposed at ``/metrics``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counters: dict[str, dict[Labels, float]] = defaultdict(dict)
        self.histograms: dict[str, dict[Labels, Histogram]] = defaultdict(dict)
        self.help: dict[str, str] = {}

    def inc(self, name: str, value: float = 1.0, help: str = "", **labels: str) -> None:
        """Add ``value`` to a counter."""
        key = tuple(sorted(labels.items()))
        with self._lock:
            self.help.setdefault(name, help)
            self.counters[name][key] = self.counters[name].get(key, 0.0) + value

    def observe(self, name: str, value: float, help: str = "", **labels: str) -> None:
        """Record one measurement in a histogram."""
        key = tuple(sorted(labels.items()))
        with self._lock:
            self.help.setdefault(name, help)
            self.histograms[name].setdefault(key, Histogram()).observe(value)

    def record_review(self, result: ReviewResult) -> None:
        """Count a finished review: status, duration, stage timings, findings, tokens."""
        self.inc("sentinel_reviews_total", help="Reviews finished", status=result.status.value)
        self.observe("sentinel_review_duration_ms", result.duration_ms, help="Total review latency")
        for stage in result.stages:
            if stage.duration_ms is not None and stage.status is not StageStatus.PENDING:
                self.observe(
                    "sentinel_stage_duration_ms",
                    stage.duration_ms,
                    help="Latency per pipeline stage",
                    stage=stage.name.value,
                )
        files = result.summary.stats.files_reviewed
        self.inc("sentinel_files_analyzed_total", files, help="Files reviewed")
        for f in result.all_findings():
            status = f.verification.status.value if f.verification else "none"
            self.inc(
                "sentinel_findings_total",
                help="Findings by source and verification",
                source=f.source.value,
                verification=status,
            )
        self.inc(
            "sentinel_ai_tokens_total",
            result.usage.input_tokens,
            help="AI tokens",
            direction="input",
        )
        self.inc("sentinel_ai_tokens_total", result.usage.output_tokens, direction="output")

    def record_fix(
        self, status: str, duration_ms: float, check_results: Iterable[tuple[str, str]] = ()
    ) -> None:
        """Count a fix attempt, its duration, and each validation check's result.

        ``check_results`` are ``(check name, status)`` pairs, e.g. ``("tests", "failed")``;
        they give the fix success rate and the test failure rate the spec asks for.
        """
        self.inc("sentinel_fix_attempts_total", help="Fix attempts by outcome", status=status)
        self.observe("sentinel_fix_duration_ms", duration_ms, help="Fix generation+validation")
        for check, result in check_results:
            self.inc(
                "sentinel_fix_checks_total",
                help="Fix validation checks by outcome",
                check=check,
                status=result,
            )

    def render(self) -> str:
        """Everything in the Prometheus text exposition format."""
        lines: list[str] = []
        with self._lock:
            for name, series in sorted(self.counters.items()):
                lines += [f"# HELP {name} {self.help.get(name, '')}", f"# TYPE {name} counter"]
                for labels, value in series.items():
                    lines.append(f"{name}{_fmt(labels)} {value:g}")
            for name, hseries in sorted(self.histograms.items()):
                lines += [f"# HELP {name} {self.help.get(name, '')}", f"# TYPE {name} histogram"]
                for labels, values in hseries.items():
                    for b, count in zip(BUCKETS_MS, values.buckets, strict=True):
                        lines.append(f"{name}_bucket{_fmt((*labels, ('le', str(b))))} {count}")
                    lines.append(f"{name}_bucket{_fmt((*labels, ('le', '+Inf')))} {values.count}")
                    lines.append(f"{name}_sum{_fmt(labels)} {values.total:g}")
                    lines.append(f"{name}_count{_fmt(labels)} {values.count}")
        return "\n".join(lines) + "\n"


def _fmt(labels: Labels) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{k}="{v}"' for k, v in labels)
    return "{" + inner + "}"


METRICS = Metrics()
