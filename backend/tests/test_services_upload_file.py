import io
from datetime import timedelta
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

from my_org.file_db import db as dbmod
from my_org.file_db import permissions
from my_org.file_db.cleanup import CleanupManager
from my_org.file_db.config import DELETE_REASON_USER
from my_org.file_db.datasource import DatasourceManager
from my_org.file_db.metadata import MetadataManager
from my_org.file_db.models import FileDeleteLog, _utcnow
from my_org.file_db.query_engine import FileQueryEngine
from my_org.file_db.services.file_service import FileService
from my_org.file_db.services.upload_service import UploadService
from my_org.file_db.storage.local import LocalStorageBackend
from my_org.file_db.upload import UploadManager

CSV_TEXT = "id,name\n1,alice\n2,bob\n"  # 23 bytes -> 3 chunks of 8


def setup_function():
    dbmod.reset_db()
    dbmod.init_db("sqlite://")


def teardown_function():
    dbmod.reset_db()


def _user(uid="u1"):
    return SimpleNamespace(
        id=uid, username=f"user-{uid}", roles=[], permissions=set(), is_anonymous=False
    )


def _env(tmp_path, monkeypatch, uid="u1"):
    storage = LocalStorageBackend(base_path=str(tmp_path / "files"))
    metadata = MetadataManager(dbmod.get_session())
    engine = FileQueryEngine(storage, metadata, parquet_dir=str(tmp_path / "parquet"))
    upload_mgr = UploadManager(storage, metadata)
    datasource = DatasourceManager(metadata, engine)
    cleanup = CleanupManager(storage, metadata, datasource, engine)
    upload_svc = UploadService(upload_mgr, storage, metadata)
    file_svc = FileService(metadata, storage, engine, cleanup, datasource)
    monkeypatch.setattr(permissions, "current_user", lambda: _user(uid))
    return upload_svc, file_svc, storage, metadata, engine


def _upload(upload_svc, data: bytes, filename="a.csv", file_type="csv", chunk_size=8):
    init = upload_svc.init(
        "u1",
        {
            "filename": filename,
            "file_type": file_type,
            "total_size": len(data),
            "chunk_size": chunk_size,
        },
    )
    upload_id = init["upload_id"]
    for i in range(0, len(data), chunk_size):
        upload_svc.chunk("u1", upload_id, i // chunk_size, data[i : i + chunk_size])
    return upload_svc.complete("u1", upload_id)["file_id"]


def _xlsx_bytes():
    wb = Workbook()
    ws = wb.active
    ws.title = "S0"
    ws.append(["id"])
    ws.append([1])
    ws2 = wb.create_sheet("S1")
    ws2.append(["id"])
    ws2.append([2])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_upload_full_flow(tmp_path, monkeypatch):
    upload_svc, file_svc, storage, metadata, engine = _env(tmp_path, monkeypatch)
    file_id = _upload(upload_svc, CSV_TEXT.encode())  # 3 chunks

    types = {c["name"]: c["type"] for c in metadata.get_column_types(file_id)}
    assert types == {"id": "integer", "name": "string"}  # schema parsed at complete

    record = metadata.get_file(file_id)
    assert record.file_type == "csv"
    assert record.row_count == 2
    assert record.column_count == 2


def test_chunk_and_status(tmp_path, monkeypatch):
    upload_svc, file_svc, storage, metadata, engine = _env(tmp_path, monkeypatch)
    init = upload_svc.init(
        "u1", {"filename": "a.csv", "file_type": "csv", "total_size": 23, "chunk_size": 8}
    )
    assert set(init) >= {"upload_id", "chunk_size", "total_chunks"}
    assert init["total_chunks"] == 3

    upload_svc.chunk("u1", init["upload_id"], 0, b"0" * 8)
    status = upload_svc.status("u1", init["upload_id"])
    assert set(status) >= {"upload_id", "total_chunks", "received_chunks", "total_size", "status"}
    assert status["received_chunks"] == [0]

    assert upload_svc.abort("u1", init["upload_id"])["status"] == "aborted"


def test_preview_shape(tmp_path, monkeypatch):
    upload_svc, file_svc, storage, metadata, engine = _env(tmp_path, monkeypatch)
    file_id = _upload(upload_svc, CSV_TEXT.encode())

    preview = file_svc.preview("u1", file_id)
    assert preview["totalRows"] == 2
    assert len(preview["rows"]) == 2
    assert [c["name"] for c in preview["columns"]] == ["id", "name"]
    assert all("type" in c for c in preview["columns"])


def test_save_config_reparses_csv(tmp_path, monkeypatch):
    upload_svc, file_svc, storage, metadata, engine = _env(tmp_path, monkeypatch)
    file_id = _upload(upload_svc, CSV_TEXT.encode())
    before = {c["name"]: c for c in metadata.get_column_types(file_id)}
    metadata.update_column_type(file_id, before["id"]["id"], "float", changed_by="u1")

    out = file_svc.save_config(
        "u1", file_id, {"encoding": "latin-1", "datasource_name": "Sales", "description": "d"}
    )
    assert out["datasource_name"] == "Sales"

    record = metadata.get_file(file_id)
    assert record.encoding == "latin-1"
    after = {c["name"]: c for c in metadata.get_column_types(file_id)}
    assert after["id"]["type"] == "float"  # user-defined type survives re-parse
    assert after["id"]["is_user_defined"] is True
    assert after["name"]["type"] == "string"  # re-inferred
    assert after["name"]["id"] != before["name"]["id"]  # fresh columns registered


def test_save_config_excel_sheets(tmp_path, monkeypatch):
    upload_svc, file_svc, storage, metadata, engine = _env(tmp_path, monkeypatch)
    file_id = _upload(upload_svc, _xlsx_bytes(), filename="b.xlsx", file_type="excel")

    sheets = metadata.get_file(file_id).sheets
    assert [s.is_selected for s in sheets] == [False, False]
    assert metadata.get_columns(file_id, sheets[0].id)  # columns registered per sheet

    file_svc.save_config("u1", file_id, {"sheets": [1]})
    assert [s.is_selected for s in metadata.get_file(file_id).sheets] == [False, True]

    out = file_svc.save_config("u1", file_id, {"sheets": [0, 1], "datasource_name": "E"})
    assert out["sheets"] == [0, 1]


def test_owner_guard(tmp_path, monkeypatch):
    upload_svc, file_svc, storage, metadata, engine = _env(tmp_path, monkeypatch)
    file_id = _upload(upload_svc, CSV_TEXT.encode())

    monkeypatch.setattr(permissions, "current_user", lambda: _user("u2"))
    with pytest.raises(PermissionError):
        file_svc.save_config("u2", file_id, {"datasource_name": "X"})
    with pytest.raises(PermissionError):
        file_svc.delete("u2", file_id)


def test_delete_calls_cascade(tmp_path, monkeypatch):
    upload_svc, file_svc, storage, metadata, engine = _env(tmp_path, monkeypatch)
    file_id = _upload(upload_svc, CSV_TEXT.encode())
    rel = metadata.get_file(file_id).storage_path

    assert file_svc.delete("u1", file_id)["deleted"] is True
    assert metadata.get_file(file_id) is None
    assert storage.file_exists(rel) is False

    log = dbmod.get_session().query(FileDeleteLog).one()
    assert log.reason == DELETE_REASON_USER
    assert log.deleted_by == "u1"


def test_notifications_window(tmp_path, monkeypatch):
    upload_svc, file_svc, storage, metadata, engine = _env(tmp_path, monkeypatch)
    soon = _upload(upload_svc, CSV_TEXT.encode(), filename="soon.csv")
    later = _upload(upload_svc, CSV_TEXT.encode(), filename="later.csv")
    session = dbmod.get_session()
    metadata.get_file(soon).expiry_time = _utcnow() + timedelta(days=3)
    metadata.get_file(later).expiry_time = _utcnow() + timedelta(days=30)
    session.commit()

    items = file_svc.notifications("u1")
    assert [i["file_id"] for i in items] == [soon]
    assert items[0]["filename"] == "soon.csv"
    assert items[0]["days_left"] in (2, 3)
