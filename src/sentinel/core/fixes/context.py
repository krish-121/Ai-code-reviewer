"""Choose a bounded, policy-filtered multi-file context and absent test-file slots."""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sentinel.analysis.ast.registry import default_registry
from sentinel.analysis.graph.builder import build_graph
from sentinel.core.configuration.config import RepoConfig
from sentinel.core.domain.models import Finding
from sentinel.core.fixes.safety import check_fix_path
from sentinel.core.paths import RepositoryPathError, read_repository_text, repository_parent
from sentinel.core.review.orchestrator import SOURCE_EXTENSIONS
from sentinel.core.review.workspace import collect_sources


@dataclass
class FixContext:
    """Only these existing sources and absent test paths may appear in a patch."""

    files: dict[str, str]
    new_files: list[str]


def fix_context(root: Path, finding: Finding, config: RepoConfig) -> FixContext:
    """Select the target, configured files, graph neighbors and nearby tests."""
    check_fix_path(finding.file, config)
    original = read_repository_text(root, finding.file, config.fix.max_context_chars)
    snapshot = collect_sources(
        root,
        set(SOURCE_EXTENSIONS),
        [finding.file],
        ignore=config.ignore,
        languages=config.languages,
    )
    graph = build_graph(default_registry().analyze(snapshot.sources)).graph
    neighbors = set()
    for edge in graph.edges:
        source, target = graph.node(edge.source), graph.node(edge.target)
        if source is None or target is None:
            continue
        if source.file == finding.file and target.file:
            neighbors.add(target.file)
        if target.file == finding.file and source.file:
            neighbors.add(source.file)
    test_path = _test_path(finding.file, root)
    candidates = [*config.fix.context_files, test_path, *sorted(neighbors)]
    files, used = {finding.file: original}, len(original)
    for path in dict.fromkeys(candidates):
        try:
            check_fix_path(path, config)
        except RepositoryPathError:
            if path in config.fix.context_files:
                raise
            continue
        if path in files or len(files) >= config.fix.max_files:
            continue
        content = snapshot.sources.get(path)
        if content is not None and used + len(content) <= config.fix.max_context_chars:
            files[path], used = content, used + len(content)
    return FixContext(files, _new_slot(root, test_path, config))


def _test_path(path: str, root: Path) -> str:
    file = PurePosixPath(path)
    stem = file.stem.strip("_") or "module"
    if file.suffix in (".py", ".pyi"):
        name = f"test_{stem}_regression.py"
    else:
        name = f"{stem}.regression.test{file.suffix}"
    return f"tests/{name}" if (root / "tests").is_dir() else name


def _new_slot(root: Path, path: str, config: RepoConfig) -> list[str]:
    try:
        check_fix_path(path, config)
        with repository_parent(root, path):
            if not (root / path).exists() and not (root / path).is_symlink():
                return [path]
    except (OSError, RepositoryPathError):
        return []
    return []


def analysis_targets(root: Path, config: RepoConfig) -> list[str]:
    """Collect all eligible validation inputs, refusing an incomplete source inventory."""
    snapshot = collect_sources(
        root, set(SOURCE_EXTENSIONS), [], ignore=config.ignore, languages=config.languages
    )
    if snapshot.truncated or snapshot.unreadable:
        raise RepositoryPathError("validation source inventory is incomplete")
    return sorted(snapshot.sources)
