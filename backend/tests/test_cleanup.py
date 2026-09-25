import io
import uuid
from datetime import timedelta
from pathlib import Path

from my_org.file_db import cleanup as cleanup_mod
from my_org.file_db import db as dbmod
from my_org.file_db.cleanup import CleanupManager
from my_org.file_db.config import (
    DELETE_REASON_ADMIN,
    DELETE_REASON_EXPIRED,
    DELETE_REASON_USER,
)
from my_org.file_db.datasource import DatasourceManager
from my_org.file_db.metadata import MetadataManager
from my_org.file_db.models import FileDeleteLog, _utcnow
from my_org.file_db.query_engine import FileQueryEngine, view_name
from my_org.file_db.storage.local import LocalStorageBackend


def setup_function():
    dbmod.reset_db()
    dbmod.init_db("sqlite://")
    cleanup_mod._last_run = 0.0


def teardown_function():
    dbmod.reset_db()


def _env(tmp_path, host_fakes):
    storage = LocalStorageBackend(base_path=str(tmp_path / "files"))
    metadata = MetadataManager(dbmod.get_session())
    engine = FileQueryEngine(storage, metadata, parquet_dir=str(tmp_path / "parquet"))
    datasource = DatasourceManager(metadata, engine)
    cleanup = CleanupManager(storage, metadata, datasource, engine)
    return cleanup, datasource, storage, metadata, engine


def _seed(tmp_path, storage, metadata, filename="a.csv", created_by="u1"):
    file_id = str(uuid.uuid4())
    text = "id,name\n1,x\n"
    rel = storage.save_file(io.BytesIO(text.encode("utf-8")), created_by, file_id, filename)
    metadata.create_file_record(
        file_id=file_id,
        created_by=created_by,
        filename=filename,
        file_size=len(text),
        file_type="csv",
        storage_path=rel,
        encoding="utf-8",
        delimiter=",",
    )
    return file_id, rel


def _set_expiry(metadata, file_id, delta):
    record = metadata.get_file(file_id)
    record.expiry_time = _utcnow() + delta
    dbmod.get_session().commit()


def test_delete_file_cascade_full(tmp_path, host_fakes):
    cleanup, datasource, storage, metadata, engine = _env(tmp_path, host_fakes)
    file_id, rel = _seed(tmp_path, storage, metadata)
    engine.ensure_view(file_id)
    parquet_dir = Path(engine.parquet_dir) / file_id
    parquet_dir.mkdir(parents=True)
    (parquet_dir / "0.parquet").touch()
    datasource.create_datasource(
        file_id=file_id, datasource_name="X", created_by="u1", database_id=1
    )

    assert cleanup.delete_file_cascade(file_id, DELETE_REASON_USER, "u1") is True

    assert storage.file_exists(rel) is False
    assert not parquet_dir.exists()
    assert metadata.get_file(file_id) is None
    assert datasource.list_for_file(file_id) == []
    assert host_fakes.tables() == []

    views = [
        r[0]
        for r in engine.get_connection().execute("SELECT view_name FROM duckdb_views()").fetchall()
    ]
    assert view_name(file_id) not in views

    logs = dbmod.get_session().query(FileDeleteLog).all()
    assert len(logs) == 1
    assert logs[0].reason == DELETE_REASON_USER
    assert logs[0].deleted_by == "u1"
    assert logs[0].filename == "a.csv"


def test_expire_due_files(tmp_path, host_fakes):
    cleanup, datasource, storage, metadata, engine = _env(tmp_path, host_fakes)
    overdue, _ = _seed(tmp_path, storage, metadata, filename="old.csv")
    fresh, _ = _seed(tmp_path, storage, metadata, filename="new.csv")
    _set_expiry(metadata, overdue, timedelta(days=-1))

    deleted = cleanup.expire_due_files()
    assert deleted == [overdue]
    assert metadata.get_file(overdue) is None
    assert metadata.get_file(fresh) is not None

    logs = dbmod.get_session().query(FileDeleteLog).all()
    assert len(logs) == 1
    assert logs[0].reason == DELETE_REASON_EXPIRED
    assert logs[0].deleted_by == "system"


def test_manual_delete_reason(tmp_path, host_fakes):
    cleanup, datasource, storage, metadata, engine = _env(tmp_path, host_fakes)
    file_id, _ = _seed(tmp_path, storage, metadata)

    assert cleanup.manual_delete_file(file_id, "admin1") is True
    log = dbmod.get_session().query(FileDeleteLog).one()
    assert log.reason == DELETE_REASON_ADMIN
    assert log.deleted_by == "admin1"


def test_auto_cleanup_throttled(tmp_path, host_fakes):
    cleanup, datasource, storage, metadata, engine = _env(tmp_path, host_fakes)
    a, _ = _seed(tmp_path, storage, metadata, filename="a.csv")
    _set_expiry(metadata, a, timedelta(days=-1))
    assert cleanup.run_auto_cleanup() == [a]

    b, _ = _seed(tmp_path, storage, metadata, filename="b.csv")
    _set_expiry(metadata, b, timedelta(days=-1))
    assert cleanup.run_auto_cleanup() == []  # throttled: b survives
    assert metadata.get_file(b) is not None

    assert cleanup.run_auto_cleanup(force=True) == [b]  # force bypasses throttle


def test_upcoming_expiries(tmp_path, host_fakes):
    cleanup, datasource, storage, metadata, engine = _env(tmp_path, host_fakes)
    soon, _ = _seed(tmp_path, storage, metadata, filename="soon.csv")
    soon2, _ = _seed(tmp_path, storage, metadata, filename="soon2.csv", created_by="u2")
    later, _ = _seed(tmp_path, storage, metadata, filename="later.csv")
    _set_expiry(metadata, soon, timedelta(days=3))
    _set_expiry(metadata, soon2, timedelta(days=5))
    _set_expiry(metadata, later, timedelta(days=30))

    assert {f.id for f in cleanup.upcoming_expiries()} == {soon, soon2}
    assert [f.id for f in cleanup.upcoming_expiries(user_id="u1")] == [soon]


def test_missing_file_idempotent(tmp_path, host_fakes):
    cleanup, datasource, storage, metadata, engine = _env(tmp_path, host_fakes)
    assert cleanup.delete_file_cascade("nope", DELETE_REASON_USER, "u1") is False
    assert dbmod.get_session().query(FileDeleteLog).count() == 0
