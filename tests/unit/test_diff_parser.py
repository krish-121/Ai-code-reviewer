"""Unified-diff parsing: file kinds, hunks, line numbers and unsafe paths."""

from __future__ import annotations

import pytest

from sentinel.analysis.diff.parser import (
    UnsafePathError,
    detect_language,
    parse_unified_diff,
    render_file_diff,
    safe_path,
    whole_file_change,
)
from sentinel.core.domain.models import ChangeType, Language, LineKind

MODIFIED = """\
diff --git a/src/app.py b/src/app.py
index 83db48f..bf269f4 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,5 +1,6 @@ import os
 import os
-def f(x):
-    return x
+def f(x, y):
+    total = x + y
+    return total

 print(f(1))
@@ -20,3 +21,3 @@ def g():
     a = 1
-    b = 2
+    b = 3
     return a + b
"""


def test_parses_modified_file_with_two_hunks() -> None:
    cs = parse_unified_diff(MODIFIED)
    assert len(cs.files) == 1
    f = cs.files[0]
    assert f.path == "src/app.py"
    assert f.change_type is ChangeType.MODIFIED
    assert f.language is Language.PYTHON
    assert len(f.hunks) == 2
    assert f.additions == 4
    assert f.deletions == 3
    assert f.added_lines() == {2, 3, 4, 22}
    assert f.changed_ranges() == [(2, 4), (22, 22)]
    assert f.hunks[0].header == "import os"
    ctx = [ln for ln in f.hunks[0].lines if ln.kind is LineKind.CONTEXT]
    assert ctx[0].old_lineno == 1 and ctx[0].new_lineno == 1


def test_touches_and_distance() -> None:
    f = parse_unified_diff(MODIFIED).files[0]
    assert f.touches(3, 3)
    assert not f.touches(10, 12)
    assert f.touches(10, 12, slack=10)
    assert f.distance_to_change(20) == 2


def test_added_deleted_renamed_binary() -> None:
    text = """\
diff --git a/new.ts b/new.ts
new file mode 100644
index 0000000..e69de29
--- /dev/null
+++ b/new.ts
@@ -0,0 +1,2 @@
+export const a = 1;
+export const b = 2;
diff --git a/old.js b/old.js
deleted file mode 100644
--- a/old.js
+++ /dev/null
@@ -1 +0,0 @@
-console.log(1)
diff --git a/lib/a.py b/lib/b.py
similarity index 100%
rename from lib/a.py
rename to lib/b.py
diff --git a/logo.png b/logo.png
new file mode 100644
Binary files /dev/null and b/logo.png differ
"""
    cs = parse_unified_diff(text)
    by_path = {f.path: f for f in cs.files}
    assert by_path["new.ts"].change_type is ChangeType.ADDED
    assert by_path["new.ts"].language is Language.TYPESCRIPT
    assert by_path["new.ts"].added_lines() == {1, 2}
    assert by_path["old.js"].change_type is ChangeType.DELETED
    assert by_path["old.js"].deletions == 1
    renamed = by_path["lib/b.py"]
    assert renamed.change_type is ChangeType.RENAMED
    assert renamed.old_path == "lib/a.py"
    assert by_path["logo.png"].is_binary


def test_no_newline_marker_and_crlf() -> None:
    text = (
        "diff --git a/x.py b/x.py\r\n--- a/x.py\r\n+++ b/x.py\r\n@@ -1 +1 @@\r\n-a\r\n"
        "\\ No newline at end of file\r\n+b\r\n\\ No newline at end of file\r\n"
    )
    f = parse_unified_diff(text).files[0]
    assert [ln.content for ln in f.hunks[0].lines] == ["a", "b"]


def test_plain_diff_u_multiple_files() -> None:
    text = """\
--- a/one.py
+++ b/one.py
@@ -1 +1 @@
-x = 1
+x = 2
--- a/two.py
+++ b/two.py
@@ -1 +1 @@
-y = 1
+y = 2
"""
    cs = parse_unified_diff(text)
    assert [f.path for f in cs.files] == ["one.py", "two.py"]


def test_removed_line_that_looks_like_header() -> None:
    text = """\
diff --git a/q.sql b/q.sql
--- a/q.sql
+++ b/q.sql
@@ -1,2 +1,1 @@
--- a comment in SQL
 select 1;
"""
    f = parse_unified_diff(text).files[0]
    assert f.deletions == 1
    assert f.hunks[0].lines[0].content == "-- a comment in SQL"


def test_path_traversal_is_rejected() -> None:
    text = """\
diff --git a/../../etc/passwd b/../../etc/passwd
--- a/../../etc/passwd
+++ b/../../etc/passwd
@@ -1 +1 @@
-root
+pwned
"""
    cs = parse_unified_diff(text)
    assert cs.files == []
    assert cs.skipped and "unsafe path" in cs.skipped[0].reason


@pytest.mark.parametrize("bad", ["/etc/passwd", "../x", "a/../../x", "C:/win", "a\x00b", "."])
def test_safe_path_rejects_absolute_and_escaping_paths(bad: str) -> None:
    with pytest.raises(UnsafePathError):
        safe_path(bad)


def test_safe_path_normalizes_separators_and_dots() -> None:
    assert safe_path("a/./b//c.py") == "a/b/c.py"
    assert safe_path("a\\b.py") == "a/b.py"


def test_quoted_unicode_path() -> None:
    text = (
        'diff --git "a/caf\\303\\251.py" "b/caf\\303\\251.py"\n'
        '--- "a/caf\\303\\251.py"\n+++ "b/caf\\303\\251.py"\n@@ -1 +1 @@\n-a\n+b\n'
    )
    assert parse_unified_diff(text).files[0].path == "café.py"


def test_language_is_detected_from_extension() -> None:
    assert detect_language("a/B.TSX") is Language.TYPESCRIPT
    assert detect_language("x.mjs") is Language.JAVASCRIPT
    assert detect_language("README.md") is Language.OTHER


def test_roundtrip_render() -> None:
    f = parse_unified_diff(MODIFIED).files[0]
    again = parse_unified_diff("diff --git a/src/app.py b/src/app.py\n" + render_file_diff(f))
    assert again.files[0].added_lines() == f.added_lines()


def test_whole_file_change() -> None:
    f = whole_file_change("pkg/mod.py", "a = 1\nb = 2\n")
    assert f.change_type is ChangeType.ADDED
    assert f.added_lines() == {1, 2}
    assert whole_file_change("empty.py", "").hunks == []


def test_truncated_hunk_does_not_crash() -> None:
    text = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1,5 +1,5 @@\n a\n-b\n"
    f = parse_unified_diff(text).files[0]
    assert f.deletions == 1
