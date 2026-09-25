"""FileService: listing/preview/config/usage/deletion orchestration."""

from __future__ import annotations

import csv
from datetime import timedelta

from .. import permissions
from ..config import DELETE_REASON_USER, EXPIRY_WARNING_DAYS
from ..models import _utcnow
from ..parsers import csv_parser


def _file_dict(record) -> dict:
    return {
        "id": record.id,
        "filename": record.filename,
        "file_size": record.file_size,
        "file_type": record.file_type,
        "status": record.status,
        "created_by": record.created_by,
        "upload_time": record.upload_time.isoformat(),
        "expiry_time": record.expiry_time.isoformat(),
        "row_count": record.row_count,
        "column_count": record.column_count,
        "sheet_count": record.sheet_count,
        "encoding": record.encoding,
        "delimiter": record.delimiter,
    }


class FileService:
    def __init__(self, metadata, storage, engine, cleanup, datasource):
        self.metadata = metadata
        self.storage = storage
        self.engine = engine
        self.cleanup = cleanup
        self.datasource = datasource

    def list(self, user_id: str) -> list[dict]:
        return [_file_dict(r) for r in self.metadata.get_user_files(user_id)]

    def get(self, user_id: str, file_id: str) -> dict:
        record = self._get(file_id)
        data = _file_dict(record)
        data["sheets"] = [
            {
                "id": s.id,
                "name": s.sheet_name,
                "index": s.sheet_index,
                "row_count": s.row_count,
                "column_count": s.column_count,
                "selected": s.is_selected,
            }
            for s in record.sheets
        ]
        return data

    def preview(self, user_id: str, file_id: str, sheet_index: int | None = None) -> dict:
        self._get(file_id)
        return self.engine.preview(file_id, sheet_index)

    def save_config(self, user_id: str, file_id: str, config: dict) -> dict:
        record = self._get(file_id)
        permissions.check_file_owner(record)
        name = config.get("datasource_name")
        if name is not None and not str(name).strip():
            raise ValueError("datasource_name must not be empty")

        if record.file_type == "csv":
            delimiter = config.get("delimiter") or record.delimiter
            encoding = config.get("encoding") or record.encoding
            if delimiter != record.delimiter or encoding != record.encoding:
                record.delimiter, record.encoding = delimiter, encoding
                self._reparse_csv(record)
        else:
            selected = config.get("sheets")
            if selected is not None:
                wanted = set(selected)
                for sheet in record.sheets:
                    sheet.is_selected = sheet.sheet_index in wanted
        self.metadata.session.commit()
        return {
            "file_id": file_id,
            "datasource_name": name,
            "description": config.get("description"),
            "delimiter": record.delimiter,
            "encoding": record.encoding,
            "sheets": [s.sheet_index for s in record.sheets if s.is_selected],
        }

    def usage(self, user_id: str, file_id: str) -> dict:
        self._get(file_id)
        return self.datasource.usage_info(file_id)

    def delete(self, user_id: str, file_id: str) -> dict:
        record = self._get(file_id)
        permissions.check_file_owner(record)
        deleted = self.cleanup.delete_file_cascade(file_id, DELETE_REASON_USER, user_id)
        return {"deleted": deleted, "file_id": file_id}

    def notifications(self, user_id: str) -> list[dict]:
        now = _utcnow()
        items = []
        for record in self.cleanup.upcoming_expiries(user_id, EXPIRY_WARNING_DAYS):
            items.append(
                {
                    "file_id": record.id,
                    "filename": record.filename,
                    "expiry_time": record.expiry_time.isoformat(),
                    "days_left": (record.expiry_time - now).days,
                }
            )
        return items

    def _reparse_csv(self, record) -> None:
        user_types = {
            c.column_name: (c.column_type, c.column_format)
            for c in record.columns
            if c.is_user_defined
        }
        path = self.storage.get_file_path(record.storage_path)
        try:
            schema = csv_parser.parse_schema(path, record.encoding, record.delimiter)
            row_count = csv_parser.count_rows(path, record.encoding, record.delimiter)
        except (UnicodeDecodeError, csv.Error) as exc:
            raise ValueError(f"cannot parse file with given encoding: {exc}") from exc

        for column in list(record.columns):
            self.metadata.session.delete(column)
        self.metadata.session.flush()
        self.metadata.create_columns(record.id, schema.columns)

        for column in record.columns:
            if column.column_name in user_types:
                column.column_type, column.column_format = user_types[column.column_name]
                column.is_user_defined = True
        record.row_count = row_count
        record.column_count = len(schema.columns)
        self.engine.invalidate(record.id)

    def _get(self, file_id: str):
        record = self.metadata.get_file(file_id)
        if record is None:
            raise KeyError(f"unknown file: {file_id!r}")
        return record
