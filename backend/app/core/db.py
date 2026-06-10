"""Database engine and session management.

Synchronous SQLAlchemy 2.0 throughout (see ADR-002): handlers run in the
FastAPI threadpool, services stay simple, and the audit chain's advisory
locking is straightforward to reason about.
"""

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for platform-schema mapped classes."""


class TenantBase(DeclarativeBase):
    """Declarative base for tenant-schema tables.

    Tables are declared without a schema; at runtime every query runs
    through a connection whose `schema_translate_map` maps None to the
    current tenant's schema (see ADR-003). Provisioning creates these
    tables in each new tenant schema at the current head state.
    """


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Return the process-wide engine, creating it on first use."""
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the process-wide session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory


def reset_engine() -> None:
    """Dispose of the engine so the next use re-reads settings (tests only)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def session_scope() -> Iterator[Session]:
    """Yield a session outside the request cycle (CLI, jobs)."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def tenant_session(schema_name: str) -> Session:
    """A session whose unqualified tables resolve to one tenant's schema.

    Platform tables carry an explicit schema and are unaffected; tenant
    tables (TenantBase) translate to `schema_name`. The caller owns commit
    and close.
    """
    engine = get_engine().execution_options(schema_translate_map={None: schema_name})
    return Session(bind=engine, expire_on_commit=False)
