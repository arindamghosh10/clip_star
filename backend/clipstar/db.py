from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings


@lru_cache
def get_engine() -> Engine:
    s = get_settings()
    return create_engine(s.database_url, pool_pre_ping=True, pool_size=10, max_overflow=10, future=True)


@lru_cache
def _factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


def new_session() -> Session:
    return _factory()()


@contextmanager
def session_scope() -> Iterator[Session]:
    """One transaction: commit on success, roll back on any error."""
    s = new_session()
    try:
        yield s
        s.commit()
    except BaseException:
        s.rollback()
        raise
    finally:
        s.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency. Endpoints commit explicitly, so a failed commit
    becomes an error response instead of being lost after the response is sent."""
    s = new_session()
    try:
        yield s
    except BaseException:
        s.rollback()
        raise
    finally:
        s.close()
