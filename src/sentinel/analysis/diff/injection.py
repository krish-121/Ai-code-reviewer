"""Detect prompt-injection text planted in source code.

Code under review is untrusted input to the AI reviewer. Comments or strings addressed
to an AI ("ignore previous instructions", "do not report this") are reported as a
deterministic security finding, independently of what the model does with them.
"""

from __future__ import annotations

import re

from sentinel.core.domain.models import (
    Category,
    ChangeSet,
    Evidence,
    Finding,
    FindingSource,
    LineKind,
    Severity,
)

PATTERNS = [
    re.compile(p, re.I)
    for p in (
        r"ignore (all |any )?(the |your )?(previous|prior|above|earlier|preceding) "
        r"(instructions|prompts?|rules|directions)",
        r"disregard (all |any )?(the |your )?(previous|prior|above|earlier|system) .{0,20}"
        r"(instructions|prompts?|rules)",
        r"\b(you are now|from now on you are|act as) (an? )?(ai|assistant|chatgpt|claude|gpt|"
        r"llm|language model|reviewer|code reviewer)\b",
        r"\b(ai|llm|reviewer|assistant)s?\b.{0,40}\b(do not|don't|never) (report|flag|mention|"
        r"comment on)\b",
        r"\b(do not|don't|never) (report|flag|mention) (this|these|any) (issue|finding|problem|"
        r"vulnerabilit)",
        r"\breveal (your |the )?(system prompt|instructions|secrets|api keys?)\b",
        r"\b(approve|lgtm) (this|the) (pr|pull request|change|diff)\b.{0,40}\b(ai|reviewer|bot)\b",
        r"<\s*/?\s*(system|assistant)\s*>",
    )
]


def scan_for_injection(changeset: ChangeSet) -> list[Finding]:
    findings: list[Finding] = []
    for change in changeset.files:
        for hunk in change.hunks:
            for ln in hunk.lines:
                if ln.kind is not LineKind.ADDED or ln.new_lineno is None:
                    continue
                if not any(p.search(ln.content) for p in PATTERNS):
                    continue
                snippet = ln.content.strip()[:120]
                findings.append(
                    Finding(
                        category=Category.SECURITY,
                        severity=Severity.MEDIUM,
                        confidence=0.75,
                        title="Prompt-injection text in source",
                        explanation=(
                            "This line contains text addressed to an AI reviewer or assistant. "
                            "Automated reviewers and coding agents may follow such text as an "
                            "instruction. Sentinel treats it as data, but other tools reading "
                            "this repository may not."
                        ),
                        file=change.path,
                        line_start=ln.new_lineno,
                        line_end=ln.new_lineno,
                        evidence=[
                            Evidence(
                                source="sentinel:prompt-injection",
                                text=snippet,
                                file=change.path,
                                line=ln.new_lineno,
                            )
                        ],
                        suggested_fix="Remove the instruction-like text from the code.",
                        source=FindingSource.STATIC_ANALYZER,
                        origins=["sentinel:prompt-injection"],
                        rule_id="sentinel/prompt-injection",
                        tags=["prompt-injection"],
                    )
                )
    return findings
