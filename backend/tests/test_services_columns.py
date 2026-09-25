import json
import uuid
from types import SimpleNamespace

import pytest

from my_org.file_db import db as dbmod
from my_org.file_db import permissions
from my_org.file_db.metadata import MetadataManager
from my_org.file_db.parsers.schema import ColumnSchema
from my_org.file_db.query_engine import FileQueryEngine
from my_org.file_db.services.column_service import ColumnService
from my_org.file_db.storage.local import LocalStorageBackend


def setup_function():
    dbmod.reset_db()
    dbmod.init_db("sqlite://")


def teardown_function():
    dbmod.reset_db()


def _user(uid="u1"):
    return SimpleNamespace(
        id=uid, username=f"user-{uid}", roles=[], permissions=set(), is_anonymous=False
    )


def _env(tmp_path, monkeypatch):
    storage = LocalStorageBackend(base_path=str(tmp_path / "files"))
    metadata = MetadataManager(dbmod.get_session())
    engine = FileQueryEngine(storage, metadata, parquet_dir=str(tmp_path / "parquet"))
    monkeypatch.setattr(permissions, "current_user", lambda: _user("u1"))
    return ColumnService(metadata, engine), metadata, engine


def _seed(metadata):
    file_id = str(uuid.uuid4())
    metadata.create_file_record(
        file_id=file_id,
        created_by="u1",
        filename="t.csv",
        file_size=1,
        file_type="csv",
        storage_path=f"u1/{file_id}/t.csv",
    )
    metadata.create_columns(
        file_id,
        [
            ColumnSchema(name="amount", column_type="string", sample_values=["1.5"]),
            ColumnSchema(name="day", column_type="string", sample_values=["2026-09-25"]),
        ],
    )
    return file_id


class StubDatasource:
    def __init__(self):
        self.synced = []

    def sync_columns(self, file_id):
        self.synced.append(file_id)
        return 1


def test_column_changes_sync_dataset_columns(tmp_path, monkeypatch):
    svc0, metadata, engine = _env(tmp_path, monkeypatch)
    stub = StubDatasource()
    svc = ColumnService(metadata, engine, stub)
    file_id = _seed(metadata)
    col_id = metadata.get_columns(file_id)[0].id

    svc.update("u1", file_id, col_id, "float")
    svc.import_config(
        "u1", file_id, {"columns": [{"name": "day", "type": "datetime", "format": "%Y-%m-%d"}]}
    )

    # every schema change re-syncs the host dataset columns
    assert stub.synced == [file_id, file_id]


def test_update_invalidates_and_logs_history(tmp_path, monkeypatch):
    svc, metadata, engine = _env(tmp_path, monkeypatch)
    file_id = _seed(metadata)
    col_id = metadata.get_columns(file_id)[0].id

    invalidated = []
    monkeypatch.setattr(engine, "invalidate", lambda fid: invalidated.append(fid))

    out = svc.update("u1", file_id, col_id, "float")
    assert out["type"] == "float"
    assert invalidated == [file_id]

    history = svc.history("u1", file_id)
    assert len(history) == 1
    assert history[0]["old_type"] == "string"
    assert history[0]["new_type"] == "float"
    assert history[0]["changed_by"] == "u1"

    assert [c["name"] for c in svc.list("u1", file_id)] == ["amount", "day"]

    with pytest.raises(KeyError):
        svc.update("u1", file_id, "missing", "float")


def test_import_config_rejects_wholesale(tmp_path, monkeypatch):
    svc, metadata, engine = _env(tmp_path, monkeypatch)
    file_id = _seed(metadata)

    with pytest.raises(ValueError):
        svc.import_config(
            "u1",
            file_id,
            {"columns": [{"name": "amount", "type": "float"}, {"name": "nope", "type": "string"}]},
        )
    with pytest.raises(ValueError):
        svc.import_config("u1", file_id, "{not json")

    current = {c["name"]: c for c in svc.list("u1", file_id)}
    assert current["amount"]["type"] == "string"  # nothing partially written
    assert svc.history("u1", file_id) == []


def test_import_config_applies_all(tmp_path, monkeypatch):
    svc, metadata, engine = _env(tmp_path, monkeypatch)
    file_id = _seed(metadata)
    invalidated = []
    monkeypatch.setattr(engine, "invalidate", lambda fid: invalidated.append(fid))

    out = svc.import_config(
        "u1",
        file_id,
        json.dumps(
            {
                "columns": [
                    {"name": "amount", "type": "float"},
                    {"name": "day", "type": "datetime", "format": "%Y-%m-%d"},
                ]
            }
        ),
    )
    assert out == {"applied": 2}
    current = {c["name"]: c for c in svc.list("u1", file_id)}
    assert current["amount"]["type"] == "float"
    assert current["day"]["format"] == "%Y-%m-%d"
    assert len(svc.history("u1", file_id)) == 2
    assert invalidated == [file_id]
