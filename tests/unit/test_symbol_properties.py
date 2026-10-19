"""Opaque result fields are unknown, while invented free function calls still fail."""

import pytest

from sentinel.core.verification.checks import SymbolEvidenceCheck
from tests.unit.test_verification import ctx, finding


@pytest.mark.parametrize(
    "explanation",
    [
        "The rejected outcome's `reason` is discarded.",
        "The library-provided `result.payload` is never inspected.",
        "The external client uses `client.dynamic_method(value)`.",
    ],
)
def test_unknown_properties_are_neutral_instead_of_invented_functions(explanation: str) -> None:
    result = SymbolEvidenceCheck().check(finding(explanation=explanation), ctx())
    assert result is not None
    assert result.outcome == "neutral" and not result.decisive
    assert "unresolved" in result.detail


@pytest.mark.parametrize(
    "explanation",
    [
        "`validate_sql()` and `escape_all()` are skipped.",
        "validate_sql(query) then escape_all(query) are called.",
    ],
)
def test_invented_bare_function_calls_still_contradict_evidence(explanation: str) -> None:
    result = SymbolEvidenceCheck().check(finding(explanation=explanation), ctx())
    assert result is not None and result.outcome == "contradicts" and result.decisive


def test_existing_repository_symbols_still_supply_structural_evidence() -> None:
    result = SymbolEvidenceCheck().check(finding(explanation="`find_user()` uses `connect`"), ctx())
    assert result is not None and result.outcome == "supports"
