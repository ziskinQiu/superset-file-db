"""ColumnService: column type editing, JSON import and change history."""

from __future__ import annotations

import json

from .. import permissions


class ColumnService:
    def __init__(self, metadata, engine, datasource=None):
        self.metadata = metadata
        self.engine = engine
        self.datasource = datasource

    def _sync_datasets(self, file_id: str) -> None:
        if self.datasource is not None:
            self.datasource.sync_columns(file_id)

    def list(self, user_id: str, file_id: str, sheet_id: str | None = None) -> list[dict]:
        return [
            {
                "id": c.id,
                "name": c.column_name,
                "type": c.column_type,
                "format": c.column_format,
                "is_user_defined": c.is_user_defined,
                "sample_values": json.loads(c.sample_values or "[]"),
            }
            for c in self.metadata.get_columns(file_id, sheet_id)
        ]

    def update(
        self,
        user_id: str,
        file_id: str,
        column_id: str,
        column_type: str,
        column_format: str | None = None,
    ) -> dict:
        permissions.check_file_owner(self._get_file(file_id))
        if not self.metadata.update_column_type(
            file_id, column_id, column_type, column_format, changed_by=user_id
        ):
            raise KeyError(f"unknown column: {column_id!r}")
        self.engine.invalidate(file_id)
        self._sync_datasets(file_id)
        return next(c for c in self.list(user_id, file_id) if c["id"] == column_id)

    def import_config(self, user_id: str, file_id: str, config_json) -> dict:
        permissions.check_file_owner(self._get_file(file_id))
        if isinstance(config_json, str):
            try:
                config_json = json.loads(config_json)
            except ValueError as exc:
                raise ValueError(f"invalid JSON config: {exc}") from exc
        applied = self.metadata.import_column_config(file_id, config_json, changed_by=user_id)
        self.engine.invalidate(file_id)
        self._sync_datasets(file_id)
        return {"applied": applied}

    def history(self, user_id: str, file_id: str) -> list[dict]:
        self._get_file(file_id)
        return [
            {
                "column_name": log.column_name,
                "old_type": log.old_type,
                "new_type": log.new_type,
                "old_format": log.old_format,
                "new_format": log.new_format,
                "changed_by": log.changed_by,
                "changed_at": log.changed_at.isoformat(),
            }
            for log in self.metadata.list_column_change_logs(file_id)
        ]

    def _get_file(self, file_id: str):
        record = self.metadata.get_file(file_id)
        if record is None:
            raise KeyError(f"unknown file: {file_id!r}")
        return record
