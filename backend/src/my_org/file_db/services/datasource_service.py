"""DatasourceService: dataset creation, connection listing and cleanup entry."""

from __future__ import annotations

from .. import permissions
from ..models import FileDatasource


class DatasourceService:
    def __init__(self, metadata, datasource, cleanup):
        self.metadata = metadata
        self.datasource = datasource
        self.cleanup_mgr = cleanup

    def connections(self, user_id: str) -> list[dict]:
        return self.datasource.available_connections()

    def create(
        self,
        user_id: str,
        file_id: str,
        sheet_indices,
        name: str,
        description: str | None = None,
        database_id: int | None = None,
    ) -> list[dict]:
        if not permissions.can_create_datasource():
            raise PermissionError("dataset creation not permitted")
        record = self._get_file(file_id)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("datasource name must not be empty")

        connections = self.datasource.available_connections()
        if database_id is None:
            if not connections:
                raise ValueError("no 'File Database' connection configured")
            database_id = connections[0]["id"]

        indices = list(sheet_indices) if sheet_indices else [None]
        if record.file_type == "excel" and indices == [None]:
            raise ValueError("sheet_indices required for Excel files")

        used = {
            r.datasource_name
            for r in self.metadata.session.query(FileDatasource).all()
        }
        created = []
        for index in indices:
            final_name = _unique_name(name, used)
            used.add(final_name)
            sheet_id = self._sheet_id(record, index)
            datasource_id = self.datasource.create_datasource(
                file_id=file_id,
                sheet_id=sheet_id,
                sheet_index=index,
                datasource_name=final_name,
                description=description,
                created_by=user_id,
                database_id=database_id,
            )
            created.append(
                {"datasource_id": datasource_id, "name": final_name, "sheet_index": index}
            )
        return created

    def list_for_file(self, user_id: str, file_id: str) -> list[dict]:
        self._get_file(file_id)
        return [
            {
                "id": r.id,
                "datasource_id": r.datasource_id,
                "datasource_name": r.datasource_name,
                "sheet_id": r.sheet_id,
                "created_at": r.created_at.isoformat(),
            }
            for r in self.datasource.list_for_file(file_id)
        ]

    def cleanup(self, user_id: str, force: bool = False) -> dict:
        if force and not permissions.is_admin():
            raise PermissionError("manual cleanup is admin-only")
        return {"deleted": self.cleanup_mgr.run_auto_cleanup(force=force)}

    def _get_file(self, file_id: str):
        record = self.metadata.get_file(file_id)
        if record is None:
            raise KeyError(f"unknown file: {file_id!r}")
        return record

    @staticmethod
    def _sheet_id(record, sheet_index):
        if sheet_index is None:
            return None
        for sheet in record.sheets:
            if sheet.sheet_index == sheet_index:
                return sheet.id
        raise ValueError(f"unknown sheet index: {sheet_index}")


def _unique_name(base: str, used: set) -> str:
    if base not in used:
        return base
    n = 2
    while f"{base}_{n}" in used:
        n += 1
    return f"{base}_{n}"
