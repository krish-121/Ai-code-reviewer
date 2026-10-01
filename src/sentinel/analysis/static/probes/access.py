"""Probes for access-control and secrets findings."""

from __future__ import annotations

import re

from sentinel.analysis.diff.secrets import scan_line
from sentinel.analysis.static.probes.common import (
    HIGH_WEIGHT,
    VERY_HIGH_WEIGHT,
    first_match,
    result,
)
from sentinel.core.domain.graph import GraphNode
from sentinel.core.domain.models import CheckOutcome, Finding, VerificationCheck
from sentinel.core.verification.engine import VerificationContext, reachability

AUTHORIZATION_RE = re.compile(
    r"\b(is_admin|is_superuser|has_perm\w*|has_role|require_role|authorize\w*|"
    r"check_permission\w*|can_access|is_owner|ensure_admin|isAdmin|hasPermission|hasRole)\b"
)
AUTHENTICATION_RE = re.compile(
    r"\b(authenticate\w*|verify_token|decode_token|validate_token|get_current_user|"
    r"login_required|verify_jwt|jwt\.decode|verify_password|check_password|verifyToken|"
    r"authenticateUser|requireAuth|getCurrentUser)\b"
)
ORDER_WORDS = ("before", "order", "prior to")
MISSING_CHECK_RE = re.compile(
    r"missing|no (authori|auth|permission)|without (authori|auth|checking)"
)
ENV_READ_RE = re.compile(r"os\.environ|os\.getenv|getenv\(|process\.env|config\[|settings\.")


class SecretProbe:
    """Is there really a credential-shaped literal on the cited line?"""

    name = "probe:secret"

    def check(self, finding: Finding, ctx: VerificationContext) -> VerificationCheck | None:
        """Scan the cited lines with the same rules the secret filter uses."""
        if "secret" not in finding.tags:
            return None
        lines = ctx.lines(finding.file)
        for number in range(max(1, finding.line_start), min(len(lines), finding.line_end) + 1):
            if scan_line(lines[number - 1], number):
                detail = f"line {number} contains a credential-shaped literal"
                return result(self.name, CheckOutcome.SUPPORTS, detail, VERY_HIGH_WEIGHT)
        cited = lines[finding.line_start - 1] if 0 < finding.line_start <= len(lines) else ""
        if ENV_READ_RE.search(cited):
            detail = "the value is read from the environment/configuration, not hard-coded"
            return result(
                self.name, CheckOutcome.CONTRADICTS, detail, VERY_HIGH_WEIGHT, decisive=True
            )
        for number in (finding.line_start - 1, finding.line_end + 1):  # off-by-one citations
            if 0 < number <= len(lines) and scan_line(lines[number - 1], number):
                detail = f"line {number} contains a credential-shaped literal"
                return result(self.name, CheckOutcome.SUPPORTS, detail, HIGH_WEIGHT)
        return None


class AuthOrderProbe:
    """Authorization before authentication, or a missing authorization check."""

    name = "probe:auth"

    def check(self, finding: Finding, ctx: VerificationContext) -> VerificationCheck | None:
        """Find the auth calls in the cited function (and on its path from an entry point)."""
        if "auth" not in finding.tags:
            return None
        node = ctx.enclosing(finding)
        if node is None or node.line_start is None or node.line_end is None:
            return None
        claim = f"{finding.title} {finding.explanation}".lower()
        if any(word in claim for word in ORDER_WORDS):
            return self._check_order(node, ctx)
        if MISSING_CHECK_RE.search(claim):
            return self._check_missing(node, finding, ctx)
        return None

    def _check_order(self, node: GraphNode, ctx: VerificationContext) -> VerificationCheck | None:
        """Claim: authorization runs before authentication."""
        lines = _node_lines(node, ctx)
        authorization = first_match(lines, AUTHORIZATION_RE, node.line_start or 1)
        authentication = first_match(lines, AUTHENTICATION_RE, node.line_start or 1)
        if not (authorization and authentication):
            return None
        (authz_line, authz_call), (authn_line, authn_call) = authorization, authentication
        if authz_line < authn_line:
            detail = (
                f"`{authz_call}` (line {authz_line}) runs before `{authn_call}` (line {authn_line})"
            )
            return result(self.name, CheckOutcome.SUPPORTS, detail, VERY_HIGH_WEIGHT)
        detail = (
            f"`{authn_call}` (line {authn_line}) already runs before `{authz_call}` "
            f"(line {authz_line})"
        )
        return result(self.name, CheckOutcome.CONTRADICTS, detail, VERY_HIGH_WEIGHT, decisive=True)

    def _check_missing(
        self, node: GraphNode, finding: Finding, ctx: VerificationContext
    ) -> VerificationCheck | None:
        """Claim: there is no authorization check on the way to this code."""
        path = ctx.graph.path_from_entrypoint(node.id) or []
        on_path = [node, *(n for n in path if n.file and n.line_start and n.line_end)]
        for candidate in on_path:
            hit = first_match(
                _node_lines(candidate, ctx), AUTHORIZATION_RE, candidate.line_start or 1
            )
            if hit:
                detail = (
                    f"authorization is checked by `{hit[1]}` in `{candidate.name}` (line {hit[0]})"
                )
                return result(self.name, CheckOutcome.CONTRADICTS, detail, HIGH_WEIGHT)
        label, _ = reachability(finding, ctx)
        if label == "entrypoint":
            detail = "no authorization check on the path from the entry point"
            return result(self.name, CheckOutcome.SUPPORTS, detail, HIGH_WEIGHT)
        return None


def _node_lines(node: GraphNode, ctx: VerificationContext) -> list[str]:
    """The source lines of a graph node."""
    return ctx.lines(node.file or "")[(node.line_start or 1) - 1 : node.line_end or 0]
