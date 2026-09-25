"""MetadataManager: file/column/sheet records and audit logs."""

import json
import uuid
from datetime import timedelta

from .config import COLUMN_TYPES, FILE_EXPIRY_DAYS, FILE_STATUS_ACTIVE
from .models import (
    ColumnTypeChangeLog,
    FileColumn,
    FileDeleteLog,
    FileSheet,
    UploadedFile,
    _utcnow,
)
from .parsers.schema import ColumnSchema, SheetSchema


class MetadataManager:
    def __init__(self, session):
        self.session = session

    def create_file_record(
        self,
        *,
        created_by: str,
        filename: str,
        file_size: int,
        file_type: str,
        storage_path: str,
        encoding: str | None = None,
        delimiter: str | None = None,
        sheet_count: int = 1,
        file_id: str | None = None,
    ) -> str:
        file_id = file_id or str(uuid.uuid4())
        upload_time = _utcnow()
        self.session.add(
            UploadedFile(
                id=file_id,
                created_by=created_by,
                filename=filename,
                file_size=file_size,
                file_type=file_type,
                storage_path=storage_path,
                upload_time=upload_time,
                expiry_time=upload_time + timedelta(days=FILE_EXPIRY_DAYS),
                status=FILE_STATUS_ACTIVE,
                sheet_count=sheet_count,
                encoding=encoding,
                delimiter=delimiter,
            )
        )
        self._commit()
        return file_id

    def create_sheets(self, file_id: str, sheets: list[SheetSchema]) -> list[str]:
        ids = []
        for sheet in sheets:
            sheet_id = str(uuid.uuid4())
            self.session.add(
                FileSheet(
                    id=sheet_id,
                    file_id=file_id,
                    sheet_name=sheet.name,
                    sheet_index=sheet.index,
                    row_count=sheet.row_count,
                    column_count=sheet.column_count,
                    is_selected=False,
                )
            )
            ids.append(sheet_id)
        self._commit()
        return ids

    def create_columns(
        self, file_id: str, columns: list[ColumnSchema], sheet_id: str | None = None
    ) -> list[str]:
        ids = []
        for order, col in enumerate(columns):
            col_id = str(uuid.uuid4())
            self.session.add(
                FileColumn(
                    id=col_id,
                    file_id=file_id,
                    sheet_id=sheet_id,
                    column_name=col.name,
                    column_type=col.column_type,
                    column_format=col.column_format,
                    column_order=order,
                    is_nullable=col.is_nullable,
                    sample_values=json.dumps(col.sample_values, ensure_ascii=False),
                    is_user_defined=False,
                )
            )
            ids.append(col_id)
        self._commit()
        return ids

    def get_file(self, file_id: str) -> UploadedFile | None:
        return self.session.get(UploadedFile, file_id)

    def get_user_files(self, user_id: str, status: str = FILE_STATUS_ACTIVE) -> list[UploadedFile]:
        return (
            self.session.query(UploadedFile)
            .filter_by(created_by=user_id, status=status)
            .order_by(UploadedFile.upload_time.desc())
            .all()
        )

    def list_active_files(self) -> list[UploadedFile]:
        return (
            self.session.query(UploadedFile)
            .filter_by(status=FILE_STATUS_ACTIVE)
            .order_by(UploadedFile.upload_time)
            .all()
        )

    def update_file_status(self, file_id: str, status: str) -> bool:
        record = self.get_file(file_id)
        if record is None:
            return False
        record.status = status
        self._commit()
        return True

    def get_columns(self, file_id: str, sheet_id: str | None = None) -> list[FileColumn]:
        query = self.session.query(FileColumn).filter_by(file_id=file_id)
        if sheet_id is not None:
            query = query.filter_by(sheet_id=sheet_id)
        return query.order_by(FileColumn.column_order).all()

    def delete_file_record(self, file_id: str) -> bool:
        record = self.get_file(file_id)
        if record is None:
            return False
        self.session.delete(record)
        self._commit()
        return True

    def log_delete(self, file_id: str, filename: str, reason: str, deleted_by: str) -> str:
        log_id = str(uuid.uuid4())
        self.session.add(
            FileDeleteLog(
                id=log_id,
                file_id=file_id,
                filename=filename,
                deleted_at=_utcnow(),
                reason=reason,
                deleted_by=deleted_by,
            )
        )
        self._commit()
        return log_id

    def update_column_type(
        self,
        file_id: str,
        column_id: str,
        column_type: str,
        column_format: str | None = None,
        changed_by: str | None = None,
    ) -> bool:
        self._validate_column_type(column_type)
        column = self._get_column(file_id, column_id)
        if column is None:
            return False
        new_format = column_format if column_type == "datetime" else None
        self.session.add(
            ColumnTypeChangeLog(
                id=str(uuid.uuid4()),
                file_id=file_id,
                column_id=column.id,
                column_name=column.column_name,
                old_type=column.column_type,
                new_type=column_type,
                old_format=column.column_format,
                new_format=new_format,
                changed_by=changed_by or "",
                changed_at=_utcnow(),
            )
        )
        column.column_type = column_type
        column.column_format = new_format
        column.is_user_defined = True
        self._commit()
        return True

    def get_column_types(self, file_id: str) -> list[dict]:
        return [
            {
                "id": c.id,
                "name": c.column_name,
                "type": c.column_type,
                "format": c.column_format,
                "is_user_defined": c.is_user_defined,
                "sample_values": json.loads(c.sample_values or "[]"),
            }
            for c in self.get_columns(file_id)
        ]

    def list_column_change_logs(self, file_id: str) -> list[ColumnTypeChangeLog]:
        return (
            self.session.query(ColumnTypeChangeLog)
            .filter_by(file_id=file_id)
            .order_by(ColumnTypeChangeLog.changed_at.asc())
            .all()
        )

    def import_column_config(
        self, file_id: str, config: dict, changed_by: str | None = None
    ) -> int:
        entries = (config or {}).get("columns")
        if not isinstance(entries, list) or not entries:
            raise ValueError("config must contain a non-empty 'columns' list")
        by_name = {c.column_name: c for c in self.get_columns(file_id)}

        # phase 1: validate wholesale — nothing may be written on failure
        planned = []
        for entry in entries:
            name = entry.get("name") if isinstance(entry, dict) else None
            column_type = entry.get("type") if isinstance(entry, dict) else None
            column_format = entry.get("format") if isinstance(entry, dict) else None
            if name not in by_name:
                raise ValueError(f"unknown column: {name!r}")
            self._validate_column_type(column_type)
            if column_format is not None and not isinstance(column_format, str):
                raise ValueError(f"invalid format for column {name!r}")
            planned.append(
                (by_name[name], column_type, column_format if column_type == "datetime" else None)
            )

        # phase 2: apply — each change gets its own permanent history entry
        for column, column_type, column_format in planned:
            self.update_column_type(file_id, column.id, column_type, column_format, changed_by)
        return len(planned)

    def _get_column(self, file_id: str, column_id: str) -> FileColumn | None:
        return self.session.query(FileColumn).filter_by(id=column_id, file_id=file_id).one_or_none()

    @staticmethod
    def _validate_column_type(column_type: str) -> None:
        if column_type not in COLUMN_TYPES:
            raise ValueError(f"invalid column type: {column_type!r}")

    def _commit(self) -> None:
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
