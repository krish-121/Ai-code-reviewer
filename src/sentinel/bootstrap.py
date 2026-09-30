"""Composition root: wires concrete adapters into the review engine.

This is the only module that knows which concrete analyzers, probes, providers and
caches exist. The CLI, the API worker and the tests all build orchestrators here.
"""

from __future__ import annotations

from pathlib import Path

from sentinel.ai.providers.factory import create_provider
from sentinel.analysis.ast.registry import LanguageRegistry, default_registry
from sentinel.analysis.static.probes import default_probes
from sentinel.analysis.static.runner import StaticAnalysisRunner, default_analyzers
from sentinel.core.configuration.config import RepoConfig, Settings
from sentinel.core.domain.ports import AIProvider, Cache, ProgressReporter
from sentinel.core.review.orchestrator import ReviewOrchestrator
from sentinel.core.verification.checks import generic_checks
from sentinel.core.verification.engine import VerificationEngine, Verifier
from sentinel.infrastructure.storage.cache import DiskCache, MemoryCache


def default_verifier() -> VerificationEngine:
    verifiers: list[Verifier] = [*generic_checks(), *default_probes()]
    return VerificationEngine(verifiers)


def make_cache(settings: Settings | None) -> Cache:
    if settings is None:
        return MemoryCache()
    try:
        settings.cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return MemoryCache()
    return DiskCache(settings.cache_dir)


def build_orchestrator(
    settings: Settings,
    repo_config: RepoConfig,
    *,
    workspace: Path,
    ai: AIProvider | None | str = "auto",
    progress: ProgressReporter | None = None,
    cache: Cache | None = None,
    registry: LanguageRegistry | None = None,
) -> ReviewOrchestrator:
    """``ai="auto"`` creates the provider from settings; pass None to skip AI review."""
    cache = cache if cache is not None else make_cache(settings)
    registry = registry or default_registry(search_roots=(workspace,), cache=cache)
    provider = create_provider(settings, cache=cache) if ai == "auto" else ai
    runner = StaticAnalysisRunner(
        default_analyzers(registry, timeout_s=repo_config.static.timeout_s),
        disabled=repo_config.static.disabled,
    )
    return ReviewOrchestrator(
        extractor=registry,
        static_runner=runner,
        verifier=default_verifier(),
        ai=provider if not isinstance(provider, str) else None,
        config=repo_config,
        progress=progress,
    )
