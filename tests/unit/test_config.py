"""Settings and .sentinel.yml loading, validation and saving."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from sentinel.core.configuration.config import (
    ConfigError,
    RepoConfig,
    load_repo_config,
    load_settings,
    parse_repo_config,
    save_user_setting,
)
from sentinel.core.domain.models import Category, Language, Severity


def test_default_repo_config_excludes_style() -> None:
    cfg = RepoConfig()
    assert Category.STYLE not in cfg.review.enabled_categories()
    assert cfg.severity_threshold is Severity.LOW


def test_spec_example_parses() -> None:
    cfg = parse_repo_config(
        """
review:
  categories:
    - bug
    - security
    - performance
    - tests
severity_threshold: medium
ignore:
  - generated/
  - migrations/
languages:
  - python
  - typescript
"""
    )
    assert cfg.review.categories == [
        Category.BUG,
        Category.SECURITY,
        Category.PERFORMANCE,
        Category.TESTS,
    ]
    assert cfg.severity_threshold is Severity.MEDIUM
    assert cfg.ignore == ["generated/", "migrations/"]
    assert cfg.languages == [Language.PYTHON, Language.TYPESCRIPT]


def test_threshold_inside_review_and_style_opt_in() -> None:
    cfg = parse_repo_config("review:\n  severity_threshold: HIGH\n  include_style: true\n")
    assert cfg.severity_threshold is Severity.HIGH
    assert Category.STYLE in cfg.review.enabled_categories()


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ("review: [1, 2", "invalid YAML"),
        ("- a\n- b\n", "mapping"),
        ("reveiw: {}\n", "reveiw"),
        ("review:\n  categories: [bogus]\n", "categories"),
        ("severity_threshold: extreme\n", "severity_threshold"),
    ],
)
def test_invalid_configs(text: str, needle: str) -> None:
    with pytest.raises(ConfigError, match=needle):
        parse_repo_config(text)


def test_load_repo_config_from_disk(tmp_path: Path) -> None:
    assert load_repo_config(tmp_path) == RepoConfig()
    (tmp_path / ".sentinel.yaml").write_text("ignore: [vendor/]\n")
    assert load_repo_config(tmp_path).ignore == ["vendor/"]


def test_settings_env_precedence(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text('provider = "gemini"\nmodel = "from-file"\n')
    s = load_settings(cfg, env={"SENTINEL_MODEL": "from-env", "GEMINI_API_KEY": "g-key"})
    assert s.provider == "gemini"
    assert s.resolved_model == "from-env"
    assert s.api_key_for("gemini") == "g-key"
    assert s.api_key_for("claude") is None
    assert "g-key" not in repr(s)


def test_settings_sentinel_key_wins_over_vendor_var(tmp_path: Path) -> None:
    s = load_settings(
        tmp_path / "none.toml",
        env={"SENTINEL_CLAUDE_KEY": "a", "ANTHROPIC_API_KEY": "b", "SENTINEL_PROVIDER": "claude"},
    )
    assert s.api_key_for("claude") == "a"
    assert s.resolved_model.startswith("claude")


def test_settings_overrides_and_validation(tmp_path: Path) -> None:
    s = load_settings(tmp_path / "x.toml", env={}, overrides={"provider": "OLLAMA", "model": None})
    assert s.provider == "ollama"
    with pytest.raises(ConfigError, match="unknown provider"):
        load_settings(tmp_path / "x.toml", env={"SENTINEL_PROVIDER": "gpt"})
    bad = tmp_path / "bad.toml"
    bad.write_text("provider = \n")
    with pytest.raises(ConfigError):
        load_settings(bad, env={})


def test_save_user_setting_is_private(tmp_path: Path) -> None:
    path = tmp_path / "cfg" / "config.toml"
    save_user_setting("provider", "claude", path)
    save_user_setting("claude_api_key", 'k"ey', path)
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600
    s = load_settings(path, env={})
    assert s.provider == "claude"
    assert s.api_key_for("claude") == 'k"ey'
    with pytest.raises(ConfigError):
        save_user_setting("database_password", "x", path)
    with pytest.raises(ValueError, match="provider"):
        save_user_setting("provider", "nope", path)


def test_save_sandbox_transport_validates_and_preserves_settings(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    save_user_setting("gemini_api_key", "test-only-key", path)
    save_user_setting("sandbox_transport", "copy", path)
    settings = load_settings(path, env={})
    assert settings.sandbox_transport == "copy"
    assert settings.api_key_for("gemini") == "test-only-key"
    before = path.read_bytes()
    with pytest.raises(ValueError, match="sandbox_transport"):
        save_user_setting("sandbox_transport", "invalid", path)
    assert path.read_bytes() == before
