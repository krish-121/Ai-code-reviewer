"""Secret detection and redaction.

Two jobs:

1. **Detection** - report hard-coded credentials in added lines as deterministic
   security findings (never including the secret itself, only a masked preview).
2. **Redaction** - guarantee that anything sent to an AI provider has credentials
   replaced by ``[REDACTED:<rule>]``. The prompt builder runs every outgoing prompt
   through ``redact_text`` as a final guard, so a secret that slipped past filtering
   still never leaves the machine.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class SecretRule:
    """One kind of secret: a pattern plus how confident a match is."""

    id: str
    title: str
    pattern: re.Pattern[str]
    group: int = 0  # which regex group holds the secret value
    confidence: float = 0.95
    check_entropy: bool = False


def _r(p: str, flags: int = 0) -> re.Pattern[str]:
    return re.compile(p, flags)


RULES: tuple[SecretRule, ...] = (
    SecretRule(
        "private-key",
        "Private key committed",
        _r(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP |ENCRYPTED )?PRIVATE KEY-----"),
    ),
    SecretRule("aws-access-key", "Hard-coded AWS access key", _r(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    SecretRule(
        "aws-secret-key",
        "Hard-coded AWS secret key",
        _r(r"(?i)aws_?secret_?(?:access_?)?key\s*[:=]\s*[\"']?([A-Za-z0-9/+=]{40})\b"),
        group=1,
    ),
    SecretRule(
        "github-token",
        "Hard-coded GitHub token",
        _r(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})\b"),
    ),
    SecretRule("slack-token", "Hard-coded Slack token", _r(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    SecretRule("stripe-key", "Hard-coded Stripe live key", _r(r"\b[sr]k_live_[0-9A-Za-z]{20,}\b")),
    SecretRule("google-api-key", "Hard-coded Google API key", _r(r"\bAIza[0-9A-Za-z\-_]{35}\b")),
    SecretRule(
        "anthropic-key", "Hard-coded Anthropic API key", _r(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")
    ),
    SecretRule(
        "openai-key", "Hard-coded OpenAI API key", _r(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}\b")
    ),
    SecretRule(
        "jwt",
        "Hard-coded JSON Web Token",
        _r(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
        confidence=0.8,
    ),
    SecretRule(
        "connection-string",
        "Credentials in connection string",
        _r(r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^:\s/@]+:([^@\s]{3,})@"),
        group=1,
        confidence=0.85,
    ),
    SecretRule(
        "generic-secret",
        "Hard-coded secret",
        _r(
            r"(?i)\b[\w.]*(?:password|passwd|pwd|secret|api_?key|access_?key|auth_?token|"
            r"private_?key|client_?secret|token)[\w]*\b[\"']?\s*[:=]\s*[\"']([^\"'\s]{8,})[\"']"
        ),
        group=1,
        confidence=0.7,
        check_entropy=True,
    ),
)

_PLACEHOLDER_HINTS = (
    "changeme",
    "change_me",
    "example",
    "placeholder",
    "dummy",
    "your_",
    "your-",
    "xxxx",
    "****",
    "<",
    "${",
    "{{",
    "redacted",
    "os.environ",
    "process.env",
    "getenv",
    "test",
    "fake",
    "sample",
)


def shannon_entropy(value: str) -> float:
    """Bits of entropy per character; random keys score high, words low."""
    if not value:
        return 0.0
    counts = Counter(value)
    n = len(value)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def _looks_like_placeholder(value: str) -> bool:
    low = value.lower()
    if any(c in value for c in "{}$%<>()[]"):  # template/format placeholders, SQL params
        return True
    return any(h in low for h in _PLACEHOLDER_HINTS) or len(set(value)) <= 3


@dataclass(frozen=True)
class SecretMatch:
    """A secret found on one line."""

    rule: SecretRule
    line: int
    start: int
    end: int
    value: str

    @property
    def masked(self) -> str:
        """The first characters followed by asterisks, safe to show in findings."""
        head = self.value[:4]
        return f"{head}{'*' * min(12, max(4, len(self.value) - 4))}"


def scan_line(text: str, line_no: int) -> list[SecretMatch]:
    """Every secret on one line (overlapping matches are reported once)."""
    matches: list[SecretMatch] = []
    taken: list[tuple[int, int]] = []
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            start, end = m.span(rule.group)
            value = m.group(rule.group)
            if any(s < end and start < e for s, e in taken):
                continue
            if rule.check_entropy and (
                _looks_like_placeholder(value) or shannon_entropy(value) < 3.0
            ):
                continue
            taken.append((start, end))
            matches.append(SecretMatch(rule, line_no, start, end, value))
    return matches


def scan_text(text: str) -> list[SecretMatch]:
    """Every secret in a text, including multi-line private-key blocks."""
    out: list[SecretMatch] = []
    in_key_block = False
    for i, line in enumerate(text.splitlines(), start=1):
        if "-----BEGIN" in line and "PRIVATE KEY-----" in line:
            in_key_block = True
        elif in_key_block and "-----END" in line:
            in_key_block = False
            continue
        elif in_key_block:
            continue  # key body lines are covered by the BEGIN match
        out.extend(scan_line(line, i))
    return out


def redact_line(text: str) -> tuple[str, list[SecretMatch]]:
    """The line with every secret replaced by a placeholder, and the matches."""
    matches = scan_line(text, 0)
    if not matches:
        return text, []
    pieces: list[str] = []
    cursor = 0
    for m in sorted(matches, key=lambda m: m.start):
        pieces.append(text[cursor : m.start])
        pieces.append(f"[REDACTED:{m.rule.id}]")
        cursor = m.end
    pieces.append(text[cursor:])
    return "".join(pieces), matches


_KEY_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S
)


def redact_text(text: str) -> tuple[str, int]:
    """Redact every detected secret. Returns (redacted_text, number_of_redactions)."""
    count = 0

    def _block(_: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return "[REDACTED:private-key]"

    text = _KEY_BLOCK_RE.sub(_block, text)
    out_lines: list[str] = []
    for line in text.split("\n"):
        red, matches = redact_line(line)
        count += len(matches)
        out_lines.append(red)
    return "\n".join(out_lines), count
