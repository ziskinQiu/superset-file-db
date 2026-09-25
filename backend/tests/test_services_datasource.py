import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest

from my_org.file_db import cleanup as cleanup_mod
from my_org.file_db import db as dbmod
from my_org.file_db import permissions
from my_org.file_db.cleanup import CleanupManager
from my_org.file_db.datasource import DatasourceManager
from my_org.file_db.metadata import MetadataManager
from my_org.file_db.models import FileDatasource, _utcnow
from my_org.file_db.query_engine import FileQueryEngine
from my_org.file_db.services.datasource_service import DatasourceService
from my_org.file_db.storage.local import LocalStorageBackend


def setup_function():
    dbmod.reset_db()
    dbmod.init_db("sqlite://")
    cleanup_mod._last_run = 0.0


def teardown_function():
    dbmod.reset_db()


def _user(uid="u1", roles=(), perms=()):
    return SimpleNamespace(
        id=uid,
        username=f"user-{uid}",
        roles=[SimpleNamespace(name=r) for r in roles],
        permissions=set(perms),
        is_anonymous=False,
    )


def _env(tmp_path, monkeypatch, host_fakes, user=None):
    storage = LocalStorageBackend(base_path=str(tmp_path / "files"))
    metadata = MetadataManager(dbmod.get_session())
    engine = FileQueryEngine(storage, metadata, parquet_dir=str(tmp_path / "parquet"))
    datasource = DatasourceManager(metadata, engine)
    cleanup = CleanupManager(storage, metadata, datasource, engine)
    monkeypatch.setattr(permissions, "current_user", lambda: user or _user("u1"))
    return DatasourceService(metadata, datasource, cleanup), metadata, cleanup


def _seed(metadata, file_type="csv", sheets=()):
    file_id = str(uuid.uuid4())
    metadata.create_file_record(
        file_id=file_id,
        created_by="u1",
        filename="t.csv",
        file_size=1,
        file_type=file_type,
        storage_path=f"u1/{file_id}/t.csv",
        sheet_count=max(len(sheets), 1),
    )
    if sheets:
        metadata.create_sheets(file_id, sheets)
    return file_id


def test_create_requires_permission(tmp_path, monkeypatch, host_fakes):
    svc, metadata, cleanup = _env(
        tmp_path, monkeypatch, host_fakes, user=_user("u3", roles=["Gamma"])
    )
    file_id = _seed(metadata)

    with pytest.raises(PermissionError):
        svc.create("u3", file_id, [], "Sales")


def test_create_batches_sheets(tmp_path, monkeypatch, host_fakes):
    from my_org.file_db.parsers.schema import SheetSchema

    svc, metadata, cleanup = _env(
        tmp_path,
        monkeypatch,
        host_fakes,
        user=_user("u1", roles=["Alpha"], perms={"can_write on Dataset"}),
    )
    file_id = _seed(
        metadata,
        file_type="excel",
        sheets=[SheetSchema(name="S0", index=0), SheetSchema(name="S1", index=1)],
    )
    host_fakes.add_database("FD", "filedb://")

    out = svc.create("u1", file_id, [0, 1], "Sales", description="d")
    assert [o["name"] for o in out] == ["Sales", "Sales_2"]  # conflict suffix
    assert [o["sheet_index"] for o in out] == [0, 1]
    rows = dbmod.get_session().query(FileDatasource).all()
    assert len(rows) == 2
    assert all(r.datasource_name.startswith("Sales") for r in rows)


def test_name_conflict_suffix(tmp_path, monkeypatch, host_fakes):
    svc, metadata, cleanup = _env(
        tmp_path,
        monkeypatch,
        host_fakes,
        user=_user("u1", perms={"can_write on Dataset"}),
    )
    host_fakes.add_database("FD", "filedb://")
    f1 = _seed(metadata)
    f2 = _seed(metadata)

    svc.create("u1", f1, [], "Sales")
    svc.create("u1", f1, [], "Sales")  # -> Sales_2
    out = svc.create("u1", f2, [], "Sales")  # -> Sales_3
    assert [o["name"] for o in out] == ["Sales_3"]


def test_connections_filter_dialect(tmp_path, monkeypatch, host_fakes):
    svc, metadata, cleanup = _env(tmp_path, monkeypatch, host_fakes)
    host_fakes.add_database("PG", "postgresql://x")
    host_fakes.add_database("FD", "filedb://")

    conns = svc.connections("u1")
    assert [c["name"] for c in conns] == ["FD"]


def test_cleanup_permissions_and_throttle(tmp_path, monkeypatch, host_fakes):
    svc, metadata, cleanup = _env(
        tmp_path, monkeypatch, host_fakes, user=_user("u3", roles=["Gamma"])
    )
    with pytest.raises(PermissionError):
        svc.cleanup("u3", force=True)  # force is admin-only

    monkeypatch.setattr(permissions, "current_user", lambda: _user("root", roles=["Admin"]))
    a = _seed(metadata)
    metadata.get_file(a).expiry_time = _utcnow() + timedelta(days=-1)
    dbmod.get_session().commit()
    assert svc.cleanup("root", force=True) == {"deleted": [a]}

    b = _seed(metadata)
    metadata.get_file(b).expiry_time = _utcnow() + timedelta(days=-1)
    dbmod.get_session().commit()
    assert svc.cleanup("root") == {"deleted": []}  # throttled auto pass
