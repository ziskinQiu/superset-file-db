"""Service layer: orchestration + DTO assembly (composition root)."""

import threading
from dataclasses import dataclass

from .column_service import ColumnService
from .datasource_service import DatasourceService
from .file_service import FileService
from .upload_service import UploadService

_engine = None
_services = None
_build_lock = threading.Lock()


@dataclass
class Services:
    upload: "UploadService"
    files: "FileService"
    columns: "ColumnService"
    datasources: "DatasourceService"


def build_services(database_uri: str | None = None) -> Services:
    """Wire storage/metadata/engine/managers and the filedb dialect (once)."""
    global _engine, _services
    if _services is not None:
        return _services
    with _build_lock:
        if _services is not None:
            return _services
        from .. import db, dialect
        from ..cleanup import CleanupManager
        from ..datasource import DatasourceManager
        from ..host_db import get_metadata_db_uri
        from ..metadata import MetadataManager
        from ..query_engine import FileQueryEngine
        from ..storage import LocalStorageBackend
        from ..upload import UploadManager

        db.init_db(database_uri or get_metadata_db_uri())
        storage = LocalStorageBackend()
        metadata = MetadataManager(db.get_session())
        engine = FileQueryEngine(storage, metadata)
        upload_mgr = UploadManager(storage, metadata)
        datasource_mgr = DatasourceManager(metadata, engine)
        cleanup_mgr = CleanupManager(storage, metadata, datasource_mgr, engine)
        dialect.set_engine_factory(get_engine)

        _engine = engine
        _services = Services(
            upload=UploadService(upload_mgr, storage, metadata),
            files=FileService(metadata, storage, engine, cleanup_mgr, datasource_mgr),
            columns=ColumnService(metadata, engine, datasource_mgr),
            datasources=DatasourceService(metadata, datasource_mgr, cleanup_mgr),
        )
        return _services


def get_services() -> Services:
    global _services
    if _services is None:
        build_services()
    return _services


def get_engine():
    global _engine
    if _engine is None:
        build_services()
    return _engine
