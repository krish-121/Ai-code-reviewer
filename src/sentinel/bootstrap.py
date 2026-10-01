"""Composition root: wires concrete adapters into the review engine.

This is the only module that knows which concrete analyzers, probes, providers and
caches exist. The CLI, the API worker and the tests all build orchestrators here.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sentinel.ai.providers.factory import create_provider
from sentinel.analysis.ast.registry import LanguageRegistry, default_registry
from sentinel.analysis.static.probes import default_probes
from sentinel.analysis.static.runner import StaticAnalysisRunner, default_analyzers
from sentinel.core.configuration.config import RepoConfig, Settings
from sentinel.core.domain.ports import AIConfigurationError, AIProvider, Cache, ProgressReporter
from sentinel.core.fixes.engine import FixEngine, Sandbox, SyntaxChecker, python_syntax
from sentinel.core.review.orchestrator import ReviewOrchestrator
from sentinel.core.verification.checks import generic_checks
from sentinel.core.verification.engine import VerificationEngine, Verifier
from sentinel.infrastructure.storage.cache import DiskCache, MemoryCache
from sentinel.integrations.github.client import (
    GitHubAppAuth,
    GitHubClient,
    GitHubError,
    StaticToken,
)
from sentinel.sandbox.runners import DockerSandbox, ProcessSandbox


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
    trusted_workspace: bool = True,
) -> ReviewOrchestrator:
    """``ai="auto"`` creates the provider from settings; pass None to skip AI review.

    ``trusted_workspace=False`` (pull requests from GitHub) guarantees that nothing
    shipped inside the reviewed repository is executed: no project-local linters, no
    type-checker plugins, no TypeScript package from its node_modules.
    """
    cache = cache if cache is not None else make_cache(settings)
    roots = (workspace,) if trusted_workspace else ()
    registry = registry or default_registry(search_roots=roots, cache=cache)
    provider = create_provider(settings, cache=cache) if ai == "auto" else ai
    runner = StaticAnalysisRunner(
        default_analyzers(
            registry, timeout_s=repo_config.static.timeout_s, trust_workspace=trusted_workspace
        ),
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


def build_sandbox(settings: Settings) -> Sandbox | None:
    """Docker by default. The weaker process sandbox is used only when explicitly allowed."""
    if settings.sandbox == "docker":
        docker = DockerSandbox(settings.sandbox_image)
        if docker.is_available():
            return docker
    if settings.allow_process_sandbox:
        return ProcessSandbox()
    return None


def _ts_syntax(registry: LanguageRegistry) -> SyntaxChecker:
    def check(path: str, content: str) -> str | None:
        if not path.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")):
            return None
        fs = registry.analyze({path: content}).get(path)
        if fs is not None and fs.failed_to_parse:
            return f"{path}: {fs.parse_error}"
        return None

    return check


def build_fix_engine(
    settings: Settings,
    repo_config: RepoConfig,
    *,
    workspace: Path,
    ai: AIProvider | None | str = "auto",
    sandbox: Sandbox | None | str = "auto",
    trusted_workspace: bool = True,
) -> FixEngine:
    provider = create_provider(settings) if ai == "auto" else ai
    if provider is None or isinstance(provider, str):
        raise AIConfigurationError(
            "Generating fixes needs an AI provider. Configure one with `sentinel config set "
            "provider claude|gemini|ollama`."
        )
    roots = (workspace,) if trusted_workspace else ()
    registry = default_registry(search_roots=roots, cache=MemoryCache())
    runner = StaticAnalysisRunner(
        default_analyzers(registry, trust_workspace=trusted_workspace),
        disabled=repo_config.static.disabled,
    )
    return FixEngine(
        provider,
        static_runner=runner,
        sandbox=build_sandbox(settings) if sandbox == "auto" else sandbox,  # type: ignore[arg-type]
        config=repo_config,
        syntax_checkers=[python_syntax, _ts_syntax(registry)],
    )


def github_factory(settings: Settings) -> Callable[[int | None], GitHubClient] | None:
    """GitHub App (preferred: short-lived, least-privilege tokens) or a static token."""
    api = settings.github_api_url
    if settings.github_app_id and settings.github_private_key_path:
        pem = Path(settings.github_private_key_path).read_text(encoding="utf-8")
        app_id = settings.github_app_id
        auths: dict[int, GitHubAppAuth] = {}

        def make_app_client(installation_id: int | None) -> GitHubClient:
            if installation_id is None:
                raise GitHubError("webhook payload has no installation id")
            auth = auths.setdefault(
                installation_id, GitHubAppAuth(app_id, pem, installation_id, api_url=api)
            )
            return GitHubClient(auth, api_url=api)

        return make_app_client
    if settings.github_token is not None:
        token = StaticToken(settings.github_token.get_secret_value())
        return lambda _installation: GitHubClient(token, api_url=api)
    return None
