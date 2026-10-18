"""Expose affected unchanged sites to the model within the existing context budget."""

from sentinel.analysis.diff.secrets import redact_text
from sentinel.core.domain.ai import ContextBlock
from sentinel.core.review.baseline import incomplete
from sentinel.core.review.state import PipelineState

CONTEXT_MARGIN = 8
BLOCK_OVERHEAD = 100


def add_impact_context(state: PipelineState, budget: int) -> None:
    """Add redacted source around new/unknown diagnostics, preserving the prompt cap."""
    if state.bundle is None:
        return
    used = sum(len(block.code) + BLOCK_OVERHEAD for block in state.bundle.blocks)
    for finding in state.static_findings:
        if finding.baseline_status not in ("introduced", "unknown"):
            continue
        if any(
            b.file == finding.file and b.line_start <= finding.line_start <= b.line_end
            for b in state.bundle.blocks
        ):
            continue
        lines = state.sources.get(finding.file, "").splitlines()
        start = max(1, finding.line_start - CONTEXT_MARGIN)
        end = min(len(lines), finding.line_end + CONTEXT_MARGIN)
        code = redact_text("\n".join(lines[start - 1 : end]))[0]
        if used + len(code) + BLOCK_OVERHEAD > budget:
            incomplete(state, "affected source omitted from AI context: context budget reached")
            state.bundle.truncated = True
            return
        state.bundle.blocks.append(
            ContextBlock(
                kind="caller",
                file=finding.file,
                line_start=start,
                line_end=end,
                code=code,
                reason="Diagnostic in a surviving file after code removal; inspect deletion impact",
            )
        )
        used += len(code) + BLOCK_OVERHEAD
