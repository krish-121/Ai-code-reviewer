# Coordinated generated fixes

Fix generation can edit multiple existing source/test files and create one explicitly
advertised regression-test file. The original repository is unchanged until Apply.

The bounded prompt includes the finding's file, graph neighbors/importers/callers,
configured additional files and an existing matching regression test. Ignore/language
rules, sensitive-file rejection, confined reads, secret redaction and prompt fencing apply
to every file. Defaults are eight existing files and 60,000 source characters.

The model may replace exact text in supplied files. It may create a regression test only
at the absent path advertised in the request, using `operation: "create"`, empty `search`,
and complete file content in `replace`. For Python the slot is
`tests/test_<module>_regression.py` when a real tests directory exists, otherwise the root
equivalent. JS/TS uses `<module>.regression.test.<extension>`. Existing files, links,
sensitive paths and arbitrary unadvertised creation paths cannot be overwritten.
Parent directories must already exist. File deletion and arbitrary new source modules are
not part of this patch protocol.

Validation runs on disposable copies. Docker reanalyzes every eligible source file before
and after the patch, checks the original issue's disappearance, rejects new serious
diagnostics and runs tests. New Python regression tests must fail against original code
and pass against patched code. Collection failures, unavailable checks and timeouts cannot
establish a validated verdict. The first Python test suite may have no pre-existing tests;
the new regression still has to demonstrate its failure before the fix.

For another framework, configure a regression command whose `{files}` argument expands
to the newly created test paths. It must exit 1 and report failing tests against original
code, then exit 0 against patched code. A runner with another failure contract needs an
adapter; without a supported command the result remains unverified. Dependency installs
belong in the trusted image, and generated tests/code never execute on the host.

```yaml
fix:
  context_files: [src/helper.py, tests/test_helper.py]
  max_files: 8
  max_context_chars: 60000
  # For a JS/TS project, adapt this to the actual installed test runner:
  regression_command: [npm, test, '--', '{files}']
```

Apply rechecks hashes of all supplied files and absence of each new file before changing
anything. New files use exclusive creation through pinned directory descriptors; symlink
and hard-link confinement still apply. An ordinary write failure attempts to restore old
contents and removes only files created by that operation. A concurrent writer's new file
is preserved. Failed rollback is reported explicitly with the affected paths.

Multiple filesystem writes are not one power-loss/process-crash transaction. Backups or
version control remain necessary, and a database commit failure after file writes may
require reconciliation. Apply requires an explicit action and a validated proposal.
Unverified proposals remain viewable/downloadable; the core writer, API, CLI and UI refuse
to apply them until validation completes. No automatic commits or pushes are performed.

Regression coverage: `tests/unit/test_multi_file_fixes.py` and the real Docker test
`test_multi_file_fix_and_created_test_validate_in_real_docker`.
