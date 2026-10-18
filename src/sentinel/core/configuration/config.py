"""Configuration.

Two separate concerns:

* ``RepoConfig`` — checked into the reviewed repository as ``.sentinel.yml``. Describes
  *what* to review (categories, thresholds, ignored paths). Contains no secrets.
* ``Settings`` — per-user/per-deployment runtime settings (provider, model, API keys,
  database URL). Loaded from ``~/.config/sentinel/config.toml`` and environment
  variables; environment wins. Never committed.
"""

from __future__ import annotations

import json
import os
import tempfile
import tomllib
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

from sentinel.core.domain.errors import SentinelError
from sentinel.core.domain.models import Category, Language, Severity


class ConfigError(SentinelError, ValueError):
    """Settings or ``.sentinel.yml`` are invalid."""


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


DEFAULT_CATEGORIES = [
    Category.BUG,
    Category.SECURITY,
    Category.PERFORMANCE,
    Category.TESTS,
    Category.ARCHITECTURE,
]


class ReviewSection(_Section):
    """``review:`` in ``.sentinel.yml``: what to look for and how much to show."""

    categories: list[Category] = Field(default_factory=lambda: list(DEFAULT_CATEGORIES))
    include_style: bool = False
    include_documentation: bool = False
    max_findings: int = Field(default=10, ge=1, le=100)
    min_confidence: float = Field(default=0.3, ge=0.0, le=1.0)
    surface_uncertain: bool = True
    max_context_chars: int = Field(default=60_000, ge=2_000)

    def enabled_categories(self) -> list[Category]:
        """The categories to review, with style/documentation only when opted in."""
        cats = list(dict.fromkeys(self.categories))
        if self.include_style and Category.STYLE not in cats:
            cats.append(Category.STYLE)
        if self.include_documentation and Category.DOCUMENTATION not in cats:
            cats.append(Category.DOCUMENTATION)
        return cats


class StaticSection(_Section):
    """``static:`` in ``.sentinel.yml``: analyzers to skip and their timeout."""

    disabled: list[str] = Field(default_factory=list, description="Analyzer names to skip")
    timeout_s: int = Field(default=120, ge=5)


class FixSection(_Section):
    """``fix:`` in ``.sentinel.yml``: how to run the tests that validate a fix."""

    test_command: list[str] | None = None
    regression_command: list[str] | None = Field(
        default=None, description="Docker command for new tests; {files} expands to their paths"
    )
    context_files: list[str] = Field(default_factory=list, max_length=20)
    max_files: int = Field(default=8, ge=1, le=20)
    max_context_chars: int = Field(default=60_000, ge=2_000)
    setup_command: list[str] | None = None

    @field_validator("setup_command")
    @classmethod
    def reject_setup(cls, value: list[str] | None) -> None:
        """Dependency setup is intentionally restricted to the trusted sandbox image."""
        if value is not None:
            raise ValueError(
                "setup_command is unsupported; install dependencies "
                "in a custom trusted sandbox image"
            )
        return

    timeout_s: int = Field(default=300, ge=10)


class RepoConfig(_Section):
    """Per-repository review configuration (``.sentinel.yml``)."""

    review: ReviewSection = Field(default_factory=ReviewSection)
    severity_threshold: Severity = Severity.LOW
    ignore: list[str] = Field(default_factory=list)
    languages: list[Language] = Field(
        default_factory=lambda: [Language.PYTHON, Language.TYPESCRIPT, Language.JAVASCRIPT]
    )
    static: StaticSection = Field(default_factory=StaticSection)
    fix: FixSection = Field(default_factory=FixSection)

    @field_validator("severity_threshold", mode="before")
    @classmethod
    def _lower(cls, v: object) -> object:
        return v.lower() if isinstance(v, str) else v


CONFIG_FILENAMES = (".sentinel.yml", ".sentinel.yaml")


def load_repo_config(root: Path) -> RepoConfig:
    """Read ``.sentinel.yml`` from the repository root (defaults when absent)."""
    for name in CONFIG_FILENAMES:
        path = root / name
        if path.is_file():
            return parse_repo_config(path.read_text(encoding="utf-8"), source=str(path))
    return RepoConfig()


def parse_repo_config(text: str, source: str = ".sentinel.yml") -> RepoConfig:
    """Validate YAML text as a ``RepoConfig``; unknown keys are errors."""
    try:
        raw = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{source}: invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{source}: expected a mapping at the top level")
    # Accept `severity_threshold` inside `review:` as well as at the top level.
    review = raw.get("review")
    if isinstance(review, dict) and "severity_threshold" in review:
        raw.setdefault("severity_threshold", review.pop("severity_threshold"))
    try:
        return RepoConfig.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise ConfigError(f"{source}: {problems}") from exc


# --------------------------------------------------------------------------- runtime settings

PROVIDERS = ("claude", "gemini", "ollama", "opencode", "none")

DEFAULT_MODELS = {
    "claude": "claude-sonnet-5-5",
    "gemini": "gemini-3.8-flash",
    "ollama": "qwen2.5-coder:7b",
    "none": "none",
    "opencode": "deepseek-v4.1-flash-free",
}

KEY_ENV_VARS: dict[str, tuple[str, ...]] = {
    "claude": ("SENTINEL_CLAUDE_KEY", "ANTHROPIC_API_KEY"),
    "gemini": ("SENTINEL_GEMINI_KEY", "GEMINI_API_KEY"),
}


class Settings(BaseModel):
    """Machine/user settings: provider, keys, database, sandbox, GitHub, server."""

    model_config = ConfigDict(extra="ignore")

    provider: str = "none"
    model: str | None = None
    temperature: float = Field(default=0.1, ge=0.0, le=1.0)
    max_tokens: int = Field(default=4096, ge=256)
    timeout_s: float = Field(default=90.0, gt=0)
    max_retries: int = Field(default=3, ge=0, le=8)
    free_fallback: bool = False
    fallback_cooldown_s: float = Field(default=300.0, gt=0, le=86_400)
    opencode_url: str = "http://127.0.0.1:4097"
    opencode_token: SecretStr | None = None
    claude_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    ollama_url: str = "http://localhost:11434"
    database_url: str = "sqlite:///" + str(Path.home() / ".sentinel" / "sentinel.db")
    cache_dir: Path = Path.home() / ".cache" / "sentinel"
    sandbox: str = Field(default="docker", description="docker | process")
    sandbox_image: str = "sentinel-sandbox:latest"
    sandbox_transport: Literal["bind", "copy"] = "bind"
    allow_process_sandbox: bool = False
    github_token: SecretStr | None = None
    github_app_id: str | None = None
    github_private_key_path: Path | None = None
    github_webhook_secret: SecretStr | None = None
    github_api_url: str = "https://api.github.com"
    auth_mode: str = Field(default="local", description="local | token")
    local_roots: str = Field(
        default="",
        description="os.pathsep-separated directories the API may review (local mode: $HOME)",
    )
    public_url: str | None = None
    log_format: str = Field(default="text", description="text | json")

    @field_validator("provider")
    @classmethod
    def _provider(cls, v: str) -> str:
        v = v.lower()
        if v not in PROVIDERS:
            raise ValueError(f"unknown provider {v!r}; expected one of {', '.join(PROVIDERS)}")
        return v

    @property
    def resolved_model(self) -> str:
        """The configured model, or the provider's default."""
        return self.model or DEFAULT_MODELS[self.provider]

    @field_validator("opencode_url")
    @classmethod
    def _opencode_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1", "opencode-bridge"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("opencode_url must name the local or Compose OpenCode bridge")
        return value.rstrip("/")

    def allowed_roots(self) -> list[Path]:
        """Directories the server may review local repositories in.

        ``SENTINEL_LOCAL_ROOTS`` when set; the home directory in local mode; none in token mode
        (multi-user servers must opt in explicitly).
        """
        if self.local_roots:
            return [Path(p).expanduser().resolve() for p in self.local_roots.split(os.pathsep) if p]
        return [Path.home().resolve()] if self.auth_mode == "local" else []

    def api_key_for(self, provider: str) -> str | None:
        """The provider credential; OpenCode uses a separate local bridge token."""
        secret = {
            "claude": self.claude_api_key,
            "gemini": self.gemini_api_key,
            "opencode": self.opencode_token,
        }.get(provider)
        return secret.get_secret_value() if secret else None


def user_config_path() -> Path:
    """Where ``sentinel config set`` stores settings (``$XDG_CONFIG_HOME`` aware)."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "sentinel" / "config.toml"


_ENV_MAP = {
    "SENTINEL_PROVIDER": "provider",
    "SENTINEL_MODEL": "model",
    "SENTINEL_TEMPERATURE": "temperature",
    "SENTINEL_MAX_TOKENS": "max_tokens",
    "SENTINEL_TIMEOUT": "timeout_s",
    "SENTINEL_FREE_FALLBACK": "free_fallback",
    "SENTINEL_OPENCODE_URL": "opencode_url",
    "SENTINEL_OPENCODE_TOKEN": "opencode_token",
    "SENTINEL_FALLBACK_COOLDOWN": "fallback_cooldown_s",
    "SENTINEL_OLLAMA_URL": "ollama_url",
    "SENTINEL_DATABASE_URL": "database_url",
    "SENTINEL_CACHE_DIR": "cache_dir",
    "SENTINEL_SANDBOX": "sandbox",
    "SENTINEL_SANDBOX_IMAGE": "sandbox_image",
    "SENTINEL_SANDBOX_TRANSPORT": "sandbox_transport",
    "SENTINEL_ALLOW_PROCESS_SANDBOX": "allow_process_sandbox",
    "SENTINEL_GITHUB_TOKEN": "github_token",
    "SENTINEL_GITHUB_APP_ID": "github_app_id",
    "SENTINEL_GITHUB_PRIVATE_KEY_PATH": "github_private_key_path",
    "SENTINEL_GITHUB_WEBHOOK_SECRET": "github_webhook_secret",
    "SENTINEL_GITHUB_API_URL": "github_api_url",
    "SENTINEL_AUTH_MODE": "auth_mode",
    "SENTINEL_LOG_FORMAT": "log_format",
    "SENTINEL_LOCAL_ROOTS": "local_roots",
    "SENTINEL_PUBLIC_URL": "public_url",
}


def load_settings(
    config_path: Path | None = None,
    env: dict[str, str] | None = None,
    overrides: dict[str, Any] | None = None,
) -> Settings:
    """Load settings. Later sources win: config file < environment < ``overrides``.

    Args:
        config_path: TOML file to read; defaults to ``~/.config/sentinel/config.toml``.
        env: Environment variables; defaults to ``os.environ`` (tests pass a dict).
        overrides: Values from command-line flags; ``None`` values are ignored.
    """
    env = dict(os.environ) if env is None else env
    data = _read_config_file(config_path or user_config_path())
    data.update(_settings_from_env(env))
    if env.get("GITHUB_TOKEN") and "github_token" not in data:
        data["github_token"] = env["GITHUB_TOKEN"]
    data.update({key: value for key, value in (overrides or {}).items() if value is not None})
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise ConfigError(f"invalid settings: {problems}") from exc


def _read_config_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def _settings_from_env(env: dict[str, str]) -> dict[str, Any]:
    """Settings given as ``SENTINEL_*`` variables, plus API keys under their usual names."""
    data: dict[str, Any] = {key: env[var] for var, key in _ENV_MAP.items() if env.get(var)}
    for provider, names in KEY_ENV_VARS.items():
        value = next((env[name] for name in names if env.get(name)), None)
        if value:
            data[f"{provider}_api_key"] = value
    return data


_WRITABLE_KEYS = {
    "provider",
    "model",
    "temperature",
    "max_tokens",
    "free_fallback",
    "fallback_cooldown_s",
    "opencode_url",
    "opencode_token",
    "claude_api_key",
    "gemini_api_key",
    "ollama_url",
    "database_url",
    "sandbox",
    "sandbox_image",
    "sandbox_transport",
    "github_token",
    "github_app_id",
    "github_private_key_path",
    "github_webhook_secret",
    "auth_mode",
}
SECRET_KEYS = {
    "claude_api_key",
    "gemini_api_key",
    "github_token",
    "github_webhook_secret",
    "opencode_token",
}


def save_user_setting(key: str, value: str, path: Path | None = None) -> Path:
    """Persist one setting to the user config file (0600 permissions: it may hold keys)."""
    if key not in _WRITABLE_KEYS:
        raise ConfigError(f"unknown setting {key!r}; settable: {', '.join(sorted(_WRITABLE_KEYS))}")
    path = path or user_config_path()
    current: dict[str, Any] = {}
    if path.is_file():
        current = tomllib.loads(path.read_text(encoding="utf-8"))
    current[key] = value
    Settings.model_validate(current)  # validate before writing
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k} = {_toml_value(v)}" for k, v in sorted(current.items())]
    content = "\n".join(lines) + "\n"
    Settings.model_validate(tomllib.loads(content))
    fd, temporary = tempfile.mkstemp(prefix=".sentinel-config-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return path


def _toml_value(v: Any) -> str:
    """Render a scalar as a TOML value."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int | float):
        return str(v)
    return json.dumps(str(v), ensure_ascii=False)
