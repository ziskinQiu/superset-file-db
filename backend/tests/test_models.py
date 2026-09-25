from datetime import datetime, timedelta

from my_org.file_db import db as dbmod
from my_org.file_db.config import (
    DELETE_REASON_USER,
    FILE_STATUS_ACTIVE,
    UPLOAD_STATUS_UPLOADING,
)
from my_org.file_db.models import (
    ColumnTypeChangeLog,
    FileColumn,
    FileDeleteLog,
    FileDatasource,
    FileSheet,
    UploadedFile,
    UploadSession,
)


def setup_function():
    dbmod.reset_db()
    dbmod.init_db("sqlite://")


def teardown_function():
    dbmod.reset_db()


def test_create_file_with_columns_and_sheets():
    session = dbmod.get_session()
    now = datetime(2026, 9, 25, 12, 0, 0)
    f = UploadedFile(
        id="f1",
        created_by="u1",
        filename="sales.csv",
        file_size=1024,
        file_type="csv",
        storage_path="u1/f1/sales.csv",
        upload_time=now,
        expiry_time=now + timedelta(days=180),
        status=FILE_STATUS_ACTIVE,
        sheet_count=1,
        column_count=2,
        encoding="utf-8",
        delimiter=",",
    )
    session.add(f)
    session.add(
        FileColumn(
            id="c1",
            file_id="f1",
            sheet_id=None,
            column_name="amount",
            column_type="float",
            column_order=0,
            is_nullable=True,
            sample_values='["1.5", "2.0"]',
            is_user_defined=False,
        )
    )
    session.add(
        FileSheet(
            id="s1",
            file_id="f1",
            sheet_name="Sheet1",
            sheet_index=0,
            row_count=10,
            column_count=2,
            is_selected=True,
        )
    )
    session.commit()

    loaded = session.get(UploadedFile, "f1")
    assert loaded.filename == "sales.csv"
    assert loaded.columns[0].column_name == "amount"
    assert loaded.sheets[0].sheet_name == "Sheet1"


def test_upload_session_roundtrip():
    session = dbmod.get_session()
    session.add(
        UploadSession(
            id="up1",
            created_by="u1",
            filename="big.xlsx",
            file_type="excel",
            total_size=100,
            chunk_size=10,
            total_chunks=10,
            received_chunks="[0, 1]",
            status=UPLOAD_STATUS_UPLOADING,
        )
    )
    session.commit()
    up = session.get(UploadSession, "up1")
    assert up.received_chunks == "[0, 1]"
    assert up.status == "uploading"


def test_log_tables_store_forever():
    session = dbmod.get_session()
    session.add(
        ColumnTypeChangeLog(
            id="l1",
            file_id="f1",
            column_id="c1",
            column_name="amount",
            old_type="string",
            new_type="float",
            changed_by="u1",
            changed_at=datetime(2026, 9, 25),
        )
    )
    session.add(
        FileDeleteLog(
            id="d1",
            file_id="f1",
            filename="sales.csv",
            deleted_at=datetime(2026, 9, 25),
            reason=DELETE_REASON_USER,
            deleted_by="u1",
        )
    )
    session.add(
        FileDatasource(
            id="ds1",
            file_id="f1",
            sheet_id=None,
            datasource_id=42,
            datasource_name="Sales",
            created_by="u1",
        )
    )
    session.commit()
    assert session.query(ColumnTypeChangeLog).count() == 1
    assert session.query(FileDeleteLog).one().reason == "user_deleted"
    assert session.query(FileDatasource).one().datasource_id == 42


def test_cascade_delete_columns_and_sheets():
    session = dbmod.get_session()
    f = UploadedFile(
        id="f2",
        created_by="u1",
        filename="a.csv",
        file_size=1,
        file_type="csv",
        storage_path="u1/f2/a.csv",
        upload_time=datetime(2026, 9, 25),
        expiry_time=datetime(2027, 3, 25),
        status=FILE_STATUS_ACTIVE,
    )
    session.add(f)
    session.add(
        FileColumn(
            id="c2",
            file_id="f2",
            column_name="x",
            column_type="string",
            column_order=0,
            sample_values="[]",
        )
    )
    session.commit()
    session.delete(f)
    session.commit()
    assert session.query(FileColumn).count() == 0
