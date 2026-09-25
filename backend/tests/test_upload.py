from pathlib import Path

import pytest

from my_org.file_db import db as dbmod
from my_org.file_db.config import (
    UPLOAD_MAX_CSV_BYTES,
    UPLOAD_MAX_EXCEL_BYTES,
    UPLOAD_STATUS_ABORTED,
    UPLOAD_STATUS_COMPLETED,
)
from my_org.file_db.metadata import MetadataManager
from my_org.file_db.storage.local import LocalStorageBackend
from my_org.file_db.upload import UploadManager


def setup_function():
    dbmod.reset_db()
    dbmod.init_db("sqlite://")


def teardown_function():
    dbmod.reset_db()


def _env(tmp_path):
    storage = LocalStorageBackend(base_path=str(tmp_path))
    metadata = MetadataManager(dbmod.get_session())
    return UploadManager(storage, metadata), storage, metadata


def test_init_validation_matrix(tmp_path):
    m, storage, metadata = _env(tmp_path)
    assert m.init_upload("u1", "data.csv", "csv", total_size=10)

    bad = [
        ("data.txt", "csv", 10),  # bad extension
        ("data.csv", "excel", 10),  # type mismatch
        ("data.xlsx", "csv", 10),  # type mismatch
        ("big.csv", "csv", UPLOAD_MAX_CSV_BYTES + 1),  # csv oversize
        ("big.xlsx", "excel", UPLOAD_MAX_EXCEL_BYTES + 1),  # excel oversize
        ("empty.csv", "csv", 0),  # empty file
        ("a" * 252 + ".csv", "csv", 10),  # filename too long
        ("bad;name.csv", "csv", 10),  # illegal char
    ]
    for filename, file_type, total_size in bad:
        with pytest.raises(ValueError):
            m.init_upload("u1", filename, file_type, total_size=total_size)


def test_chunk_order_and_idempotency(tmp_path):
    m, storage, metadata = _env(tmp_path)
    upload_id = m.init_upload("u1", "data.csv", "csv", total_size=25, chunk_size=10)

    for i in (2, 0, 1, 1):  # out of order + duplicate
        m.add_chunk(upload_id, i, f"chunk{i}".encode())

    status = m.get_status(upload_id)
    assert status["received_chunks"] == [0, 1, 2]
    assert status["total_chunks"] == 3
    assert status["total_size"] == 25
    assert status["status"] == "uploading"

    with pytest.raises(ValueError):
        m.add_chunk(upload_id, 3, b"overflow")


def test_complete_missing_chunk_fails(tmp_path):
    m, storage, metadata = _env(tmp_path)
    upload_id = m.init_upload("u1", "data.csv", "csv", total_size=30, chunk_size=10)
    m.add_chunk(upload_id, 0, b"0" * 10)
    m.add_chunk(upload_id, 2, b"2" * 10)

    with pytest.raises(ValueError) as exc:
        m.complete_upload(upload_id)
    assert "1" in str(exc.value)  # missing index listed
    assert m.get_status(upload_id)["status"] == "uploading"


def test_complete_creates_file_record(tmp_path):
    m, storage, metadata = _env(tmp_path)
    content = b"id,name\n1,alice\n"  # 16 bytes
    upload_id = m.init_upload("u1", "data.csv", "csv", total_size=len(content), chunk_size=8)
    m.add_chunk(upload_id, 1, content[8:])
    m.add_chunk(upload_id, 0, content[:8])

    file_id = m.complete_upload(upload_id)
    f = metadata.get_file(file_id)
    assert f.filename == "data.csv"
    assert f.created_by == "u1"
    assert f.file_size == len(content)
    assert f.file_type == "csv"
    assert f.encoding == "utf-8"
    assert f.delimiter == ","

    assert Path(storage.get_file_path(f.storage_path)).read_bytes() == content
    assert m.get_status(upload_id)["status"] == UPLOAD_STATUS_COMPLETED
    assert storage.delete_staging("u1", upload_id) is False  # staging cleared


def test_gbk_transcoded(tmp_path):
    m, storage, metadata = _env(tmp_path)
    text = "\n".join(["编号,姓名"] + [f"{i},张三{i}" for i in range(30)]) + "\n"
    content = text.encode("gbk")
    upload_id = m.init_upload("u1", "zh.csv", "csv", total_size=len(content), chunk_size=64)
    for i in range(0, len(content), 64):
        m.add_chunk(upload_id, i // 64, content[i : i + 64])

    file_id = m.complete_upload(upload_id)
    f = metadata.get_file(file_id)
    assert f.encoding == "utf-8"  # stored encoding after transcode
    stored = Path(storage.get_file_path(f.storage_path)).read_text(encoding="utf-8")
    assert stored == text


def test_abort_cleans_up(tmp_path):
    m, storage, metadata = _env(tmp_path)
    upload_id = m.init_upload("u1", "data.csv", "csv", total_size=10, chunk_size=5)
    m.add_chunk(upload_id, 0, b"hello")

    assert m.abort_upload(upload_id) is True
    assert m.get_status(upload_id)["status"] == UPLOAD_STATUS_ABORTED
    assert storage.delete_staging("u1", upload_id) is False  # staging cleared
    assert m.abort_upload("missing") is False
