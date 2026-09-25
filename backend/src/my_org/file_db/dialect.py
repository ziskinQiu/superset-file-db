"""SQLAlchemy `filedb` dialect + DBAPI shim routing SQL to per-file DuckDB views."""

import re
import uuid

from sqlalchemy import BigInteger, Boolean, DateTime, Float, String
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.exc import NoSuchTableError

from .config import SQLALCHEMY_TYPE_NAMES
from .query_engine import view_name

_VIEW_NAME_RE = re.compile(r"\b(file_[0-9a-f]{32}(?:_\d+)?)\b")
_VIEW_PARTS_RE = re.compile(r"file_([0-9a-f]{32})(?:_(\d+))?$")

_TYPE_CLASSES = {
    "VARCHAR": String,
    "BIGINT": BigInteger,
    "FLOAT": Float,
    "TIMESTAMP": DateTime,
    "BOOLEAN": Boolean,
}

_engine_factory = None


def set_engine_factory(fn) -> None:
    """Inject the FileQueryEngine factory (entrypoint wires the real one)."""
    global _engine_factory
    _engine_factory = fn


def _require_engine():
    if _engine_factory is None:
        raise RuntimeError("filedb engine factory not set (call set_engine_factory)")
    return _engine_factory()


class FileDBError(Exception):
    """DBAPI-style error surfaced to SQLAlchemy."""


class FileDBWarning(Exception):
    """DBAPI-style warning."""


class FileDBModule:
    """DBAPI 2.0 shim (module stand-in) backed by the shared DuckDB connection."""

    apilevel = "2.0"
    threadsafety = 1
    paramstyle = "qmark"
    Error = FileDBError
    Warning = FileDBWarning

    @staticmethod
    def connect(**kwargs):
        return FileDBConnection(**kwargs)


class FileDBConnection:
    def __init__(self, **kwargs):
        self.echo = kwargs.get("echo", False)
        self.closed = False

    def cursor(self):
        return FileDBCursor()

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self.closed = True


class FileDBCursor:
    def __init__(self):
        self._cursor = None
        self.description = None
        self.rowcount = -1

    def execute(self, operation, parameters=None):
        engine = _require_engine()
        for name in set(_VIEW_NAME_RE.findall(str(operation))):
            engine.ensure_view_by_name(name)
        self._cursor = engine.get_connection().cursor()
        if parameters is not None:
            self._cursor.execute(operation, parameters)
        else:
            self._cursor.execute(operation)
        self.description = self._cursor.description
        self.rowcount = self._cursor.rowcount
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def fetchmany(self, size=None):
        return self._cursor.fetchmany(size) if size else self._cursor.fetchmany()

    def close(self):
        self._cursor = None


class FileDBDialect(DefaultDialect):
    name = "filedb"
    driver = "duckdb"
    supports_statement_cache = False

    @classmethod
    def import_dbapi(cls):
        return FileDBModule

    dbapi = import_dbapi  # SQLAlchemy < 1.4 compat alias

    def create_connect_args(self, url):
        echo = str(url.query.get("echo", "")).lower() in ("1", "true")
        return [], {"echo": echo}

    def get_schema_names(self, connection, **kw):
        return ["main"]

    def get_table_names(self, connection, schema=None, **kw):
        return self.get_view_names(connection, schema)

    def get_view_names(self, connection, schema=None, **kw):
        names = []
        for record in _require_engine().metadata.list_active_files():
            if record.file_type == "excel":
                names.extend(view_name(record.id, s.sheet_index) for s in record.sheets if s.is_selected)
            else:
                names.append(view_name(record.id))
        return names

    def get_columns(self, connection, table_name, schema=None, **kw):
        engine = _require_engine()
        file_id, sheet_index = self._resolve(table_name)
        record = engine.metadata.get_file(file_id)
        if record is None:
            raise NoSuchTableError(table_name)
        sheet_id = None
        if sheet_index is not None:
            sheet_id = next((s.id for s in record.sheets if s.sheet_index == sheet_index), None)
            if sheet_id is None:
                raise NoSuchTableError(table_name)
        columns = engine.metadata.get_columns(file_id, sheet_id)
        if not columns:
            raise NoSuchTableError(table_name)
        return [
            {
                "name": c.column_name,
                "type": _TYPE_CLASSES[SQLALCHEMY_TYPE_NAMES[c.column_type]](),
                "nullable": c.is_nullable,
                "default": None,
            }
            for c in columns
        ]

    def has_table(self, connection, table_name, schema=None, **kw):
        return table_name in self.get_view_names(connection, schema)

    @staticmethod
    def _resolve(table_name):
        parts = _VIEW_PARTS_RE.match(table_name)
        if parts is None:
            raise NoSuchTableError(table_name)
        return str(uuid.UUID(parts.group(1))), (int(parts.group(2)) if parts.group(2) else None)
