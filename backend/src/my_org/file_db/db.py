"""Engine/session factory for extension metadata tables.

The extension owns its own declarative Base but stores tables in the
Superset PostgreSQL database (same SQLALCHEMY_DATABASE_URI).
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker

Base = declarative_base()

_engine = None
_session_factory = None


def init_db(database_uri: str, echo: bool = False) -> None:
    global _engine, _session_factory
    if _session_factory is not None:
        return
    connect_args = {}
    if database_uri.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    _engine = create_engine(database_uri, echo=echo, connect_args=connect_args)
    _session_factory = scoped_session(sessionmaker(bind=_engine))
    from . import models  # noqa: F401  register mappers

    Base.metadata.create_all(_engine)


def get_session():
    if _session_factory is None:
        raise RuntimeError("db.init_db() must be called before get_session()")
    return _session_factory


def reset_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
