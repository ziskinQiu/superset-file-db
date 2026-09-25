"""Schema dataclasses and column type inference (spec 5.9 type rules)."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Sequence

DATETIME_FORMATS = ["%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]
BOOLEAN_VALUES = {"true", "false", "yes", "no", "t", "f"}
INFER_SAMPLE_LIMIT = 200
SAMPLE_VALUES_LIMIT = 3


@dataclass
class ColumnSchema:
    name: str
    column_type: str
    column_format: str | None = None
    is_nullable: bool = True
    sample_values: list[str] = field(default_factory=list)


@dataclass
class SheetSchema:
    name: str
    index: int
    row_count: int | None = None
    column_count: int | None = None


@dataclass
class FileSchema:
    columns: list[ColumnSchema]
    sheets: list[SheetSchema]
    row_count: int | None = None


def infer_column_type(values: Sequence[str]) -> tuple[str, str | None]:
    """Infer (type, datetime_format) from the first 200 non-empty values."""
    vals = [str(v).strip() for v in values if v is not None and str(v).strip() != ""]
    vals = vals[:INFER_SAMPLE_LIMIT]
    if not vals:
        return "string", None
    if all(v.lower() in BOOLEAN_VALUES for v in vals):
        return "boolean", None
    try:
        for v in vals:
            int(v)
        return "integer", None
    except ValueError:
        pass
    try:
        for v in vals:
            float(v)
        return "float", None
    except ValueError:
        pass
    for fmt in DATETIME_FORMATS:
        try:
            for v in vals:
                datetime.strptime(v, fmt)
            return "datetime", fmt
        except ValueError:
            continue
    return "string", None


def unique_names(header: Sequence[str]) -> list[str]:
    """Column names with `_2`/`_3`... suffixes on duplicates; blanks get col_<n>."""
    seen: dict[str, int] = {}
    names: list[str] = []
    for raw in header:
        name = str(raw).strip() if raw is not None else ""
        if not name:
            name = f"col_{len(names) + 1}"
        count = seen.get(name, 0) + 1
        seen[name] = count
        names.append(name if count == 1 else f"{name}_{count}")
    return names


def build_columns(names: Sequence[str], rows: Iterable[list]) -> list[ColumnSchema]:
    """Infer per-column schema from a sample row window (empties -> nullable)."""
    windows: list[list[str]] = [[] for _ in names]
    nullable = [False] * len(names)
    for row in rows:
        for i in range(len(names)):
            v = row[i] if i < len(row) else None
            s = "" if v is None else str(v).strip()
            if not s:
                nullable[i] = True
            elif len(windows[i]) < INFER_SAMPLE_LIMIT:
                windows[i].append(s)
    columns = []
    for i, name in enumerate(names):
        ctype, cfmt = infer_column_type(windows[i])
        columns.append(
            ColumnSchema(
                name=name,
                column_type=ctype,
                column_format=cfmt,
                is_nullable=nullable[i],
                sample_values=windows[i][:SAMPLE_VALUES_LIMIT],
            )
        )
    return columns
