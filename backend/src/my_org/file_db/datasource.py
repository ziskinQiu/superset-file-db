"""DatasourceManager: register file views as Superset datasets (spec 5.1/5.10/5.12)."""

import importlib
import uuid

from . import host_db
from .models import FileDatasource
from .query_engine import view_name


class DatasourceManager:
    def __init__(self, metadata, query_engine, host_db=host_db):
        self.metadata = metadata
        self.query_engine = query_engine
        self.host_db = host_db

    def available_connections(self) -> list[dict]:
        """Admin-created 'File Database' connections the user may pick from."""
        model = self.host_db.resolve_model("Database")
        session = self.host_db.get_superset_session_factory()()
        return [
            {"id": r.id, "name": r.database_name}
            for r in session.query(model).all()
            if str(getattr(r, "sqlalchemy_uri", "")).split(":", 1)[0] == "filedb"
        ]

    def create_datasource(
        self,
        *,
        file_id: str,
        sheet_id: str | None = None,
        sheet_index: int | None = None,
        datasource_name: str,
        description: str | None = None,
        created_by: str,
        database_id: int,
    ) -> int:
        model = self.host_db.resolve_model("SqlaTable")
        session = self.host_db.get_superset_session_factory()()
        table = model()
        table.table_name = view_name(file_id, sheet_index)
        table.database_id = database_id
        table.description = description
        session.add(table)
        session.commit()
        datasource_id = table.id

        self.metadata.session.add(
            FileDatasource(
                id=str(uuid.uuid4()),
                file_id=file_id,
                sheet_id=sheet_id,
                datasource_id=datasource_id,
                datasource_name=datasource_name,
                created_by=created_by,
            )
        )
        self.metadata.session.commit()
        self.sync_columns(file_id)  # Explore needs table_columns/metrics to pick from
        self._try_add_tag(datasource_id)
        return datasource_id

    def sync_columns(self, file_id: str) -> int:
        """Re-reflect columns/metrics for every host dataset of a file.

        Superset's Explore builds its column pickers from `table_columns`, so
        datasets must be synced through the host's `fetch_metadata()` whenever
        the file schema changes.
        """
        host_session = self.host_db.get_superset_session_factory()()
        model = self.host_db.resolve_model("SqlaTable")
        count = 0
        for row in self.list_for_file(file_id):
            table = host_session.get(model, row.datasource_id)
            if table is not None:
                table.fetch_metadata()
                count += 1
        host_session.commit()
        return count

    def list_for_file(self, file_id: str) -> list[FileDatasource]:
        return self.metadata.session.query(FileDatasource).filter_by(file_id=file_id).all()

    def usage_info(self, file_id: str) -> dict:
        rows = self.list_for_file(file_id)
        ids = {r.datasource_id for r in rows}
        slices = []
        if ids:
            model = self.host_db.resolve_model("Slice")
            session = self.host_db.get_superset_session_factory()()
            slices = [s for s in session.query(model).all() if s.datasource_id in ids]
        dashboards = set()
        for s in slices:
            for d in getattr(s, "dashboards", []) or []:
                dashboards.add(d.id)
        return {"datasources": len(rows), "charts": len(slices), "dashboards": len(dashboards)}

    def delete_datasources_for_file(self, file_id: str, deleted_by: str, reason: str) -> int:
        rows = self.list_for_file(file_id)
        model = self.host_db.resolve_model("SqlaTable")
        host_session = self.host_db.get_superset_session_factory()()
        for row in rows:
            table = host_session.get(model, row.datasource_id)
            if table is not None:
                host_session.delete(table)
            self.metadata.session.delete(row)
        host_session.commit()
        self.metadata.session.commit()
        return len(rows)

    def _try_add_tag(self, datasource_id: int) -> None:
        """Best-effort Superset-native tagging; never blocks dataset creation."""
        try:
            tag_mod = importlib.import_module("superset.tags.models")
            session = self.host_db.get_superset_session_factory()()
            tag = session.query(tag_mod.Tag).filter_by(name="file-db").one_or_none()
            if tag is None:
                tag = tag_mod.Tag(name="file-db", type="custom", description="file-db datasets")
                session.add(tag)
                session.commit()
            session.add(
                tag_mod.TaggedObject(
                    tag_id=tag.id, object_id=datasource_id, object_type="dataset"
                )
            )
            session.commit()
        except Exception:
            try:
                self.host_db.get_superset_session_factory()().rollback()
            except Exception:
                pass
