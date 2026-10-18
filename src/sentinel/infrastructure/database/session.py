"""Engine/session management."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from sentinel.infrastructure.database.schema import initialize
from sentinel.infrastructure.queue.fencing import guard

SQLITE_BUSY_SECONDS = 30
SQLITE_RETRY_INTERVAL = 0.05


def normalize_url(url: str) -> str:
    """Accept ``postgres://`` URLs and select the psycopg (v3) driver."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


class Database:
    """Engine and session factory for one database URL."""

    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.url = normalize_url(url)
        kwargs: dict[str, Any] = {"echo": echo, "future": True}
        if self.url.startswith("sqlite"):
            if self.url in ("sqlite://", "sqlite:///:memory:"):
                kwargs["poolclass"] = StaticPool
            else:
                db_path = self.url.split("///", 1)[-1]
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        else:
            kwargs["pool_pre_ping"] = True
        self.engine: Engine = create_engine(self.url, **kwargs)
        if self.dialect == "sqlite":
            event.listen(self.engine, "connect", _sqlite_pragmas)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    @property
    def dialect(self) -> str:
        """``sqlite`` or ``postgresql``."""
        return self.engine.dialect.name

    def create_all(self) -> None:
        """Initialize a fresh versioned schema; require explicit upgrades for existing data."""
        initialize(self.engine)

    def session(self) -> Session:
        """A new session; the caller commits and closes it."""
        return self._sessions()

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """A session that commits on success, rolls back on error, and always closes."""
        session = self._sessions()
        try:
            guard(session)
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()


def _sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    try:
        cur.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_SECONDS * 1000}")
        cur.execute("PRAGMA foreign_keys=ON")
        _enable_wal(cur)
    finally:
        cur.close()


def _enable_wal(cursor: Any) -> None:
    deadline = time.monotonic() + SQLITE_BUSY_SECONDS
    while True:
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or time.monotonic() >= deadline:
                raise
            time.sleep(SQLITE_RETRY_INTERVAL)
