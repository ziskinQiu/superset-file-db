import pytest

from my_org.file_db import db as dbmod
from my_org.file_db.metadata import MetadataManager
from my_org.file_db.parsers.schema import ColumnSchema


def setup_function():
    dbmod.reset_db()
    dbmod.init_db("sqlite://")


def teardown_function():
    dbmod.reset_db()


def _seed():
    m = MetadataManager(dbmod.get_session())
    file_id = m.create_file_record(
        created_by="u1",
        filename="t.csv",
        file_size=1,
        file_type="csv",
        storage_path="u1/f/t.csv",
    )
    m.create_columns(
        file_id,
        [
            ColumnSchema(name="amount", column_type="string", sample_values=["1.5", "2.0"]),
            ColumnSchema(name="day", column_type="string", sample_values=["2026-09-25"]),
        ],
    )
    cols = {c.column_name: c.id for c in m.get_columns(file_id)}
    return m, file_id, cols


def test_update_column_type_writes_log():
    m, file_id, cols = _seed()
    assert m.update_column_type(file_id, cols["amount"], "float", changed_by="u1") is True

    current = {c.column_name: c for c in m.get_columns(file_id)}["amount"]
    assert current.column_type == "float"
    assert current.is_user_defined is True

    logs = m.list_column_change_logs(file_id)
    assert len(logs) == 1
    assert (logs[0].old_type, logs[0].new_type) == ("string", "float")
    assert logs[0].old_format is None and logs[0].new_format is None
    assert logs[0].column_name == "amount"
    assert logs[0].changed_by == "u1"


def test_history_accumulates():
    m, file_id, cols = _seed()
    cid = cols["amount"]
    m.update_column_type(file_id, cid, "integer", changed_by="u1")
    m.update_column_type(file_id, cid, "float", changed_by="u1")
    m.update_column_type(file_id, cid, "string", changed_by="u2")

    logs = m.list_column_change_logs(file_id)
    assert [(l.old_type, l.new_type) for l in logs] == [
        ("string", "integer"),
        ("integer", "float"),
        ("float", "string"),
    ]
    assert [l.changed_at for l in logs] == sorted(l.changed_at for l in logs)
    assert logs[-1].changed_by == "u2"


def test_invalid_type_rejected():
    m, file_id, cols = _seed()
    with pytest.raises(ValueError):
        m.update_column_type(file_id, cols["amount"], "json", changed_by="u1")
    assert m.list_column_change_logs(file_id) == []
    assert {c.column_name: c.column_type for c in m.get_columns(file_id)}["amount"] == "string"


def test_datetime_format_rules():
    m, file_id, cols = _seed()
    day = cols["day"]
    amount = cols["amount"]

    m.update_column_type(file_id, day, "datetime", column_format="%Y-%m-%d", changed_by="u1")
    col = {c.id: c for c in m.get_columns(file_id)}[day]
    assert (col.column_type, col.column_format) == ("datetime", "%Y-%m-%d")

    m.update_column_type(file_id, day, "datetime", changed_by="u1")
    assert col.column_format is None

    # non-datetime types drop any provided format
    m.update_column_type(file_id, amount, "integer", column_format="%Y", changed_by="u1")
    col = {c.id: c for c in m.get_columns(file_id)}[amount]
    assert (col.column_type, col.column_format) == ("integer", None)


def test_import_config_applies_all():
    m, file_id, cols = _seed()
    applied = m.import_column_config(
        file_id,
        {
            "columns": [
                {"name": "amount", "type": "float"},
                {"name": "day", "type": "datetime", "format": "%Y-%m-%d"},
            ]
        },
        changed_by="u1",
    )
    assert applied == 2
    current = {c.column_name: c for c in m.get_columns(file_id)}
    assert current["amount"].column_type == "float"
    assert (current["day"].column_type, current["day"].column_format) == ("datetime", "%Y-%m-%d")
    assert len(m.list_column_change_logs(file_id)) == 2


def test_import_config_rejects_wholesale():
    m, file_id, cols = _seed()

    with pytest.raises(ValueError):
        m.import_column_config(
            file_id,
            {"columns": [{"name": "amount", "type": "float"}, {"name": "missing", "type": "string"}]},
            changed_by="u1",
        )

    with pytest.raises(ValueError):
        m.import_column_config(
            file_id,
            {"columns": [{"name": "amount", "type": "json"}]},
            changed_by="u1",
        )

    current = {c.column_name: c for c in m.get_columns(file_id)}
    assert current["amount"].column_type == "string"  # untouched
    assert m.list_column_change_logs(file_id) == []  # nothing written


def test_get_column_types_shape():
    m, file_id, cols = _seed()
    m.update_column_type(file_id, cols["amount"], "datetime", column_format="%Y-%m-%d", changed_by="u1")

    types = m.get_column_types(file_id)
    assert [t["name"] for t in types] == ["amount", "day"]
    first = types[0]
    assert set(first) == {"id", "name", "type", "format", "is_user_defined", "sample_values"}
    assert first["type"] == "datetime"
    assert first["format"] == "%Y-%m-%d"
    assert first["is_user_defined"] is True
    assert first["sample_values"] == ["1.5", "2.0"]
    assert types[1]["is_user_defined"] is False
