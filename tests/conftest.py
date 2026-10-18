"""Release database pools created by tests, including short-lived CLI applications."""

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy.engine import Engine

from sentinel.infrastructure.database import session


@pytest.fixture(autouse=True)
def close_database_pools(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep pooled connections alive until explicit disposal at test teardown."""
    engines: list[Engine] = []
    create_engine = session.create_engine

    def tracked_engine(*args: Any, **kwargs: Any) -> Engine:
        engine = create_engine(*args, **kwargs)
        engines.append(engine)
        return engine

    monkeypatch.setattr(session, "create_engine", tracked_engine)
    try:
        yield
    finally:
        for engine in engines:
            engine.dispose()
