"""Eligibility checks shared by the fix engine and its delivery adapters."""

from sentinel.analysis.diff.filtering import source_exclusion_reason
from sentinel.core.configuration.config import RepoConfig
from sentinel.core.domain.models import Finding, VerificationStatus
from sentinel.core.paths import RepositoryPathError, relative_file


def check_fix_path(path: str, config: RepoConfig | None = None) -> None:
    """Reject sensitive, excluded or noncanonical paths before any file is read."""
    relative_file(path)
    reason = source_exclusion_reason(
        path, config.ignore if config else None, config.languages if config else None
    )
    if reason:
        raise RepositoryPathError(f"cannot generate/apply a fix for an excluded file: {reason}")


def check_fix_finding(finding: Finding, config: RepoConfig | None = None) -> None:
    """Rejected findings are not valid instructions for file access or generation."""
    check_fix_path(finding.file, config)
    if finding.verification and finding.verification.status is VerificationStatus.REJECTED:
        raise RepositoryPathError("cannot fix a finding rejected by verification")
