"""FileQueryEngine: shared in-memory DuckDB with one view per file/sheet.

Design note (plan Task 9): one shared connection + per-file views instead of
spec 5.14 per-file connections, so SQL Lab cross-file JOINs work; `invalidate`
drops a file's views (deletion / column-type changes).
"""

import re
import threading
import uuid
from datetime import date, datetime
from pathlib import Path

import duckdb
import pandas as pd

from .config import PARQUET_DIR_NAME, PREVIEW_ROW_LIMIT, VIEW_PREFIX, DUCKDB_TYPE_MAP
from .parsers.excel_parser import to_parquet

_VIEW_NAME_RE = re.compile(r"\b(file_[0-9a-f]{32}(?:_\d+)?)\b")
_VIEW_PARTS_RE = re.compile(r"file_([0-9a-f]{32})(?:_(\d+))?$")


def view_name(file_id: str, sheet_index: int | None = None) -> str:
    """Single source of truth for view/table naming (plan naming lock)."""
    name = f"{VIEW_PREFIX}{file_id.replace('-', '')}"
    return name if sheet_index is None else f"{name}_{sheet_index}"


class FileQueryEngine:
    def __init__(self, storage, metadata, parquet_dir: str | None = None):
        self.storage = storage
        self.metadata = metadata
        self.parquet_dir = str(
            Path(parquet_dir) if parquet_dir else Path(getattr(storage, "base_path", ".")) / PARQUET_DIR_NAME
        )
        self._conn = None
        self._lock = threading.RLock()
        self._file_views: dict[str, set[str]] = {}

    def get_connection(self) -> duckdb.DuckDBPyConnection:
        with self._lock:
            if self._conn is None:
                self._conn = duckdb.connect(":memory:")
            return self._conn

    def ensure_view(self, file_id: str, sheet_index: int | None = None) -> str:
        name = view_name(file_id, sheet_index)
        record = self.metadata.get_file(file_id)
        if record is None:
            raise KeyError(f"unknown file: {file_id!r}")
        with self._lock:
            if record.file_type == "excel":
                parquet = Path(self.parquet_dir) / file_id / f"{sheet_index}.parquet"
                if not parquet.exists():
                    parquet.parent.mkdir(parents=True, exist_ok=True)
                    to_parquet(self.storage.get_file_path(record.storage_path), sheet_index, str(parquet))
                source = f"read_parquet('{_sql_str(str(parquet))}')"
            else:
                delim = record.delimiter or ","
                source = (
                    f"read_csv_auto('{_sql_str(self.storage.get_file_path(record.storage_path))}', "
                    f"delim='{_sql_str(delim)}', header=true, all_varchar=true)"
                )
            casts = self._casts(file_id, sheet_index)
            self.get_connection().execute(f"CREATE OR REPLACE VIEW {name} AS SELECT {casts} FROM {source}")
            self._file_views.setdefault(file_id, set()).add(name)
        return name

    def ensure_view_by_name(self, name: str) -> str:
        parts = _VIEW_PARTS_RE.match(name)
        if parts is None:
            raise ValueError(f"invalid view name: {name!r}")
        file_id = str(uuid.UUID(parts.group(1)))
        sheet_index = int(parts.group(2)) if parts.group(2) else None
        return self.ensure_view(file_id, sheet_index)

    def invalidate(self, file_id: str) -> None:
        with self._lock:
            names = self._file_views.pop(file_id, set())
            for name in names:
                self.get_connection().execute(f"DROP VIEW IF EXISTS {name}")

    def query(self, file_id: str, sql: str, sheet_index: int | None = None) -> pd.DataFrame:
        if file_id is not None:
            record = self.metadata.get_file(file_id)
            if record is not None and (sheet_index is not None or record.file_type != "excel"):
                self.ensure_view(file_id, sheet_index)
        for name in set(_VIEW_NAME_RE.findall(sql)):
            self.ensure_view_by_name(name)
        with self._lock:
            return self.get_connection().execute(sql).fetchdf()

    def preview(self, file_id: str, sheet_index: int | None = None, limit: int = PREVIEW_ROW_LIMIT) -> dict:
        view = self.ensure_view(file_id, sheet_index)
        total_rows = int(self.query(file_id, f"SELECT COUNT(*) FROM {view}", sheet_index).iloc[0, 0])
        df = self.query(file_id, f"SELECT * FROM {view} LIMIT {int(limit)}", sheet_index)
        meta_types = self._column_meta(file_id, sheet_index)
        columns = [
            {
                "name": name,
                "type": meta_types.get(name, {}).get("type", _dtype_type(df[name])),
                "format": meta_types.get(name, {}).get("format"),
            }
            for name in df.columns
        ]
        rows = [[_json_cell(v) for v in row] for row in df.itertuples(index=False, name=None)]
        return {"columns": columns, "rows": rows, "totalRows": total_rows}

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
            self._conn = None
            self._file_views.clear()

    def _casts(self, file_id: str, sheet_index: int | None) -> str:
        parts = []
        for col in self._file_columns(file_id, sheet_index):
            name = _quote(col.column_name)
            if not col.is_user_defined:
                parts.append(name)
            elif col.column_type == "datetime" and col.column_format:
                fmt = _sql_str(col.column_format)
                parts.append(
                    f"COALESCE(TRY_CAST({name} AS TIMESTAMP), "
                    f"TRY_CAST(try_strptime(CAST({name} AS VARCHAR), '{fmt}') AS TIMESTAMP)) AS {name}"
                )
            elif col.column_type == "datetime":
                parts.append(f"TRY_CAST({name} AS TIMESTAMP) AS {name}")
            else:
                parts.append(f"TRY_CAST({name} AS {DUCKDB_TYPE_MAP[col.column_type]}) AS {name}")
        return ", ".join(parts) if parts else "*"

    def _file_columns(self, file_id: str, sheet_index: int | None):
        return self.metadata.get_columns(file_id, self._sheet_id(file_id, sheet_index))

    def _column_meta(self, file_id: str, sheet_index: int | None) -> dict:
        return {
            c.column_name: {"type": c.column_type, "format": c.column_format}
            for c in self._file_columns(file_id, sheet_index)
        }

    def _sheet_id(self, file_id: str, sheet_index: int | None) -> str | None:
        if sheet_index is None:
            return None
        record = self.metadata.get_file(file_id)
        for sheet in record.sheets if record is not None else []:
            if sheet.sheet_index == sheet_index:
                return sheet.id
        return None


def _quote(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _sql_str(value: str) -> str:
    return str(value).replace("'", "''")


def _dtype_type(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_integer_dtype(series):
        return "integer"
    if pd.api.types.is_float_dtype(series):
        return "float"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    return "string"


def _json_cell(value):
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value
