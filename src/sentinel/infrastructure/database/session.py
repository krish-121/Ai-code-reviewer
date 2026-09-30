"""Engine/session management."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from sentinel.infrastructure.database.models import Base


def normalize_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


class Database:
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
        return self.engine.dialect.name

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    def session(self) -> Session:
        return self._sessions()

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        session = self._sessions()
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()


def _sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()
