"""Configuration.

Two separate concerns:

* ``RepoConfig`` — checked into the reviewed repository as ``.sentinel.yml``. Describes
  *what* to review (categories, thresholds, ignored paths). Contains no secrets.
* ``Settings`` — per-user/per-deployment runtime settings (provider, model, API keys,
  database URL). Loaded from ``~/.config/sentinel/config.toml`` and environment
  variables; environment wins. Never committed.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

from sentinel.core.domain.models import Category, Language, Severity


class ConfigError(ValueError):
    pass


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
    categories: list[Category] = Field(default_factory=lambda: list(DEFAULT_CATEGORIES))
    include_style: bool = False
    include_documentation: bool = False
    max_findings: int = Field(default=10, ge=1, le=100)
    min_confidence: float = Field(default=0.3, ge=0.0, le=1.0)
    surface_uncertain: bool = True
    max_context_chars: int = Field(default=60_000, ge=2_000)

    def enabled_categories(self) -> list[Category]:
        cats = list(dict.fromkeys(self.categories))
        if self.include_style and Category.STYLE not in cats:
            cats.append(Category.STYLE)
        if self.include_documentation and Category.DOCUMENTATION not in cats:
            cats.append(Category.DOCUMENTATION)
        return cats


class StaticSection(_Section):
    disabled: list[str] = Field(default_factory=list, description="Analyzer names to skip")
    timeout_s: int = Field(default=120, ge=5)


class FixSection(_Section):
    test_command: list[str] | None = None
    setup_command: list[str] | None = None
    timeout_s: int = Field(default=300, ge=10)


class RepoConfig(_Section):
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
    for name in CONFIG_FILENAMES:
        path = root / name
        if path.is_file():
            return parse_repo_config(path.read_text(encoding="utf-8"), source=str(path))
    return RepoConfig()


def parse_repo_config(text: str, source: str = ".sentinel.yml") -> RepoConfig:
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

PROVIDERS = ("claude", "gemini", "ollama", "none")

DEFAULT_MODELS = {
    "claude": "claude-sonnet-5-5",
    "gemini": "gemini-2.5-flash",
    "ollama": "qwen2.5-coder:7b",
    "none": "none",
}

KEY_ENV_VARS: dict[str, tuple[str, ...]] = {
    "claude": ("SENTINEL_CLAUDE_KEY", "ANTHROPIC_API_KEY"),
    "gemini": ("SENTINEL_GEMINI_KEY", "GEMINI_API_KEY"),
}


class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: str = "none"
    model: str | None = None
    temperature: float = Field(default=0.1, ge=0.0, le=1.0)
    max_tokens: int = Field(default=4096, ge=256)
    timeout_s: float = Field(default=90.0, gt=0)
    max_retries: int = Field(default=3, ge=0, le=8)
    claude_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    ollama_url: str = "http://localhost:11434"
    database_url: str = "sqlite:///" + str(Path.home() / ".sentinel" / "sentinel.db")
    cache_dir: Path = Path.home() / ".cache" / "sentinel"
    sandbox: str = Field(default="docker", description="docker | process")
    sandbox_image: str = "sentinel-sandbox:latest"
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
        return self.model or DEFAULT_MODELS[self.provider]

    def allowed_roots(self) -> list[Path]:
        if self.local_roots:
            return [Path(p).expanduser().resolve() for p in self.local_roots.split(os.pathsep) if p]
        return [Path.home().resolve()] if self.auth_mode == "local" else []

    def api_key_for(self, provider: str) -> str | None:
        secret = {"claude": self.claude_api_key, "gemini": self.gemini_api_key}.get(provider)
        return secret.get_secret_value() if secret else None


def user_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "sentinel" / "config.toml"


_ENV_MAP = {
    "SENTINEL_PROVIDER": "provider",
    "SENTINEL_MODEL": "model",
    "SENTINEL_TEMPERATURE": "temperature",
    "SENTINEL_MAX_TOKENS": "max_tokens",
    "SENTINEL_TIMEOUT": "timeout_s",
    "SENTINEL_OLLAMA_URL": "ollama_url",
    "SENTINEL_DATABASE_URL": "database_url",
    "SENTINEL_CACHE_DIR": "cache_dir",
    "SENTINEL_SANDBOX": "sandbox",
    "SENTINEL_SANDBOX_IMAGE": "sandbox_image",
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
    env = dict(os.environ) if env is None else env
    data: dict[str, Any] = {}
    path = config_path or user_config_path()
    if path.is_file():
        try:
            data.update(tomllib.loads(path.read_text(encoding="utf-8")))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path}: {exc}") from exc
    for var, key in _ENV_MAP.items():
        if env.get(var):
            data[key] = env[var]
    for provider, names in KEY_ENV_VARS.items():
        for name in names:
            if env.get(name):
                data[f"{provider}_api_key"] = env[name]
                break
    if env.get("GITHUB_TOKEN") and "github_token" not in data:
        data["github_token"] = env["GITHUB_TOKEN"]
    for key, value in (overrides or {}).items():
        if value is not None:
            data[key] = value
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise ConfigError(f"invalid settings: {problems}") from exc


_WRITABLE_KEYS = {
    "provider",
    "model",
    "temperature",
    "max_tokens",
    "claude_api_key",
    "gemini_api_key",
    "ollama_url",
    "database_url",
    "sandbox",
    "sandbox_image",
    "github_token",
}
SECRET_KEYS = {"claude_api_key", "gemini_api_key", "github_token"}


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
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(path, 0o600)
    return path


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int | float):
        return str(v)
    escaped = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
