"""The one base class for errors Sentinel expects and can explain.

Every module raises its own specific error type (``GitError``, ``ConfigError``,
``ApplyError`` ...), and every one of them derives from ``SentinelError``. The edges of the
system handle them in one consistent way:

- the CLI prints the message and exits with a non-zero code (``apps/cli``),
- the API turns them into an HTTP error with the message as ``detail`` (``apps/api``),
- the review pipeline records them on the failed stage and keeps going (``core/review``).

Anything that is *not* a ``SentinelError`` is a bug and is allowed to surface with a
traceback.
"""


class SentinelError(Exception):
    """Base class for expected, user-explainable failures."""
