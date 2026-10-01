"""Deterministic verification probes.

A probe looks at the exact code a finding cites and answers a narrow question with an
AST or the extracted symbols: *is this query actually parameterized? is this function
actually async? is there really a query inside that loop?* Probes are where most
confident rejections come from — they turn "the AI said so" into "the code shows so".

Registered in ``bootstrap.default_verifier``; run by ``core/verification/engine.py``.
To add a probe: write a class with a ``name`` and a ``check(finding, ctx)`` method in one
of these modules and add it to ``default_probes`` below.
"""

from sentinel.analysis.static.probes.access import AuthOrderProbe, SecretProbe
from sentinel.analysis.static.probes.runtime import (
    AsyncProbe,
    ErrorHandlingProbe,
    NPlusOneProbe,
    QuadraticProbe,
)
from sentinel.analysis.static.probes.sql import SqlInjectionProbe
from sentinel.core.verification.engine import Verifier

__all__ = [
    "AsyncProbe",
    "AuthOrderProbe",
    "ErrorHandlingProbe",
    "NPlusOneProbe",
    "QuadraticProbe",
    "SecretProbe",
    "SqlInjectionProbe",
    "default_probes",
]


def default_probes() -> list[Verifier]:
    """Every probe, in the order the verifier runs them."""
    return [
        SqlInjectionProbe(),
        NPlusOneProbe(),
        AsyncProbe(),
        QuadraticProbe(),
        SecretProbe(),
        AuthOrderProbe(),
        ErrorHandlingProbe(),
    ]
