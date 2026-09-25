"""Lazy access to Superset host models/session.

Module top-level must never import `superset.*`: the dev venv has no Superset
package and unit tests run against injected fakes (plan Global Constraints).
"""

import importlib
import os

_MODEL_SOURCES = {
    "SqlaTable": ("superset.connectors.sqla.models", "SqlaTable"),
    "Database": ("superset.models.core", "Database"),
    "Slice": ("superset.models.slice", "Slice"),
}

_injectables = {"metadata_uri": None, "session_factory": None, "models": {}}


def set_injectables(**kwargs) -> None:
    """Inject test/runtime collaborators (None clears the slot)."""
    for key in ("metadata_uri", "session_factory", "models"):
        if key in kwargs:
            _injectables[key] = kwargs[key]


def resolve_model(name: str):
    models = _injectables["models"] or {}
    if name in models:
        return models[name]
    source = _MODEL_SOURCES.get(name)
    if source is None:
        raise RuntimeError(f"unknown host model: {name!r}")
    module_name, attr = source
    try:
        return getattr(importlib.import_module(module_name), attr)
    except (ImportError, AttributeError) as exc:
        raise RuntimeError(f"cannot resolve host model {name!r}") from exc


def get_metadata_db_uri() -> str:
    if _injectables["metadata_uri"]:
        return _injectables["metadata_uri"]
    env = os.environ.get("FILE_DB_METADATA_URI")
    if env:
        return env
    try:
        from flask import current_app

        return current_app.config["SQLALCHEMY_DATABASE_URI"]
    except Exception as exc:
        raise RuntimeError("cannot resolve metadata DB URI") from exc


def get_superset_session_factory():
    """Return a callable producing a Superset ORM session."""
    if _injectables["session_factory"] is not None:
        return _injectables["session_factory"]
    for module_name, attr in (
        # host replaces this abstract stub during Superset startup
        ("superset_core.common.models", "get_session"),
        ("superset.utils.core", "get_session"),
    ):
        try:
            get_session = getattr(importlib.import_module(module_name), attr)
        except (ImportError, AttributeError):
            continue
        try:
            get_session()  # probe: the abstract stub raises NotImplementedError
        except NotImplementedError:
            continue
        except Exception:
            pass
        return get_session
    raise RuntimeError("cannot resolve Superset session factory")
