import json
import uuid
from datetime import timedelta

from my_org.file_db import db as dbmod
from my_org.file_db.config import FILE_STATUS_ACTIVE, FILE_STATUS_EXPIRED
from my_org.file_db.metadata import MetadataManager
from my_org.file_db.models import FileColumn, FileSheet
from my_org.file_db.parsers.schema import ColumnSchema, SheetSchema


def setup_function():
    dbmod.reset_db()
    dbmod.init_db("sqlite://")


def teardown_function():
    dbmod.reset_db()


def _manager():
    return MetadataManager(dbmod.get_session())


def test_create_and_get_file():
    m = _manager()
    file_id = m.create_file_record(
        created_by="u1",
        filename="sales.csv",
        file_size=1024,
        file_type="csv",
        storage_path="u1/f1/sales.csv",
        encoding="utf-8",
        delimiter=",",
    )
    assert str(uuid.UUID(file_id)) == file_id

    f = m.get_file(file_id)
    assert f.filename == "sales.csv"
    assert f.created_by == "u1"
    assert f.file_size == 1024
    assert f.file_type == "csv"
    assert f.storage_path == "u1/f1/sales.csv"
    assert f.encoding == "utf-8"
    assert f.delimiter == ","
    assert f.status == FILE_STATUS_ACTIVE
    assert f.sheet_count == 1


def test_expiry_is_180_days():
    m = _manager()
    file_id = m.create_file_record(
        created_by="u1", filename="a.csv", file_size=1, file_type="csv", storage_path="u1/f/a.csv"
    )
    f = m.get_file(file_id)
    assert f.expiry_time - f.upload_time == timedelta(days=180)


def test_columns_and_sheets_order():
    m = _manager()
    file_id = m.create_file_record(
        created_by="u1",
        filename="b.xlsx",
        file_size=2,
        file_type="excel",
        storage_path="u1/f/b.xlsx",
        sheet_count=2,
    )
    sheet_ids = m.create_sheets(
        file_id,
        [
            SheetSchema(name="S2", index=1, row_count=5, column_count=1),
            SheetSchema(name="S1", index=0, row_count=3, column_count=2),
        ],
    )
    assert len(sheet_ids) == 2

    col_ids = m.create_columns(
        file_id,
        [
            ColumnSchema(name="z", column_type="string", sample_values=["z1", "z2"]),
            ColumnSchema(name="a", column_type="float", is_nullable=False, sample_values=["1.5", "2.0"]),
        ],
    )
    assert len(col_ids) == 2

    cols = m.get_columns(file_id)
    assert [c.column_name for c in cols] == ["z", "a"]  # column_order
    assert json.loads(cols[1].sample_values) == ["1.5", "2.0"]

    f = m.get_file(file_id)
    assert [s.sheet_name for s in f.sheets] == ["S1", "S2"]  # sheet_index
    assert [s.sheet_index for s in f.sheets] == [0, 1]


def test_user_files_filter():
    m = _manager()
    id1 = m.create_file_record(
        created_by="u1", filename="one.csv", file_size=1, file_type="csv", storage_path="u1/f1/a.csv"
    )
    id2 = m.create_file_record(
        created_by="u1", filename="two.csv", file_size=1, file_type="csv", storage_path="u1/f2/a.csv"
    )
    id3 = m.create_file_record(
        created_by="u1", filename="three.csv", file_size=1, file_type="csv", storage_path="u1/f3/a.csv"
    )
    id4 = m.create_file_record(
        created_by="u2", filename="other.csv", file_size=1, file_type="csv", storage_path="u2/f4/a.csv"
    )
    m.update_file_status(id2, FILE_STATUS_EXPIRED)

    assert [f.id for f in m.get_user_files("u1")] == [id3, id1]  # active only, newest first
    assert [f.id for f in m.get_user_files("u1", status=FILE_STATUS_EXPIRED)] == [id2]
    assert [f.id for f in m.get_user_files("u2")] == [id4]
    assert m.update_file_status("missing", FILE_STATUS_EXPIRED) is False


def test_delete_file_record_cascades():
    m = _manager()
    file_id = m.create_file_record(
        created_by="u1", filename="a.csv", file_size=1, file_type="csv", storage_path="u1/f/a.csv"
    )
    m.create_columns(file_id, [ColumnSchema(name="x", column_type="string")])
    m.create_sheets(file_id, [SheetSchema(name="S", index=0)])

    assert m.delete_file_record(file_id) is True
    session = dbmod.get_session()
    assert session.query(FileColumn).count() == 0
    assert session.query(FileSheet).count() == 0
    assert m.get_file(file_id) is None
    assert m.delete_file_record(file_id) is False
