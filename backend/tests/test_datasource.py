import uuid

from my_org.file_db import db as dbmod
from my_org.file_db.datasource import DatasourceManager
from my_org.file_db.metadata import MetadataManager
from my_org.file_db.models import FileDatasource
from my_org.file_db.query_engine import FileQueryEngine, view_name
from my_org.file_db.storage.local import LocalStorageBackend


def setup_function():
    dbmod.reset_db()
    dbmod.init_db("sqlite://")


def teardown_function():
    dbmod.reset_db()


def _env(tmp_path):
    storage = LocalStorageBackend(base_path=str(tmp_path / "files"))
    metadata = MetadataManager(dbmod.get_session())
    engine = FileQueryEngine(storage, metadata, parquet_dir=str(tmp_path / "parquet"))
    return DatasourceManager(metadata, engine), metadata, engine


def _seed_file(metadata, filename="a.csv", file_type="csv"):
    file_id = str(uuid.uuid4())
    metadata.create_file_record(
        file_id=file_id,
        created_by="u1",
        filename=filename,
        file_size=1,
        file_type=file_type,
        storage_path=f"u1/{file_id}/{filename}",
    )
    return file_id


def test_create_datasource_persists(tmp_path, host_fakes):
    ds, metadata, engine = _env(tmp_path)
    file_id = _seed_file(metadata)

    ds_id = ds.create_datasource(
        file_id=file_id,
        datasource_name="Sales",
        description="sales data",
        created_by="u1",
        database_id=7,
    )

    tables = host_fakes.tables()
    assert len(tables) == 1
    assert tables[0].id == ds_id
    assert tables[0].table_name == view_name(file_id)
    assert tables[0].database_id == 7
    assert tables[0].description == "sales data"

    rows = ds.list_for_file(file_id)
    assert len(rows) == 1
    assert rows[0].datasource_id == ds_id
    assert rows[0].datasource_name == "Sales"
    assert rows[0].created_by == "u1"


def test_create_syncs_columns_from_source(tmp_path, host_fakes):
    ds, metadata, engine = _env(tmp_path)
    file_id = _seed_file(metadata)

    ds.create_datasource(
        file_id=file_id, datasource_name="Sync", created_by="u1", database_id=1
    )
    # Explore reads columns from table_columns — they must be reflected at creation
    assert host_fakes.tables()[0].metadata_fetched is True

    assert ds.sync_columns(file_id) == 1  # re-sync keeps datasets in step with schema
    assert host_fakes.tables()[0].metadata_fetched is True


def test_view_name_mapping(tmp_path, host_fakes):
    ds, metadata, engine = _env(tmp_path)
    csv_id = _seed_file(metadata)
    excel_id = _seed_file(metadata, filename="b.xlsx", file_type="excel")

    ds.create_datasource(
        file_id=csv_id, datasource_name="C", created_by="u1", database_id=1
    )
    ds.create_datasource(
        file_id=excel_id, sheet_index=2, datasource_name="E", created_by="u1", database_id=1
    )

    names = [t.table_name for t in host_fakes.tables()]
    assert names == [view_name(csv_id), view_name(excel_id, 2)]


def test_available_connections(tmp_path, host_fakes):
    ds, metadata, engine = _env(tmp_path)
    host_fakes.add_database("PG", "postgresql://x")
    host_fakes.add_database("FD", "filedb://")
    host_fakes.add_database("FD2", "filedb://?echo=1")

    conns = ds.available_connections()
    assert [c["name"] for c in conns] == ["FD", "FD2"]
    assert all(isinstance(c["id"], int) for c in conns)


def test_usage_info(tmp_path, host_fakes):
    ds, metadata, engine = _env(tmp_path)
    file_id = _seed_file(metadata)
    ds_id = ds.create_datasource(
        file_id=file_id, datasource_name="U", created_by="u1", database_id=1
    )
    host_fakes.add_slice("s1", ds_id, dashboard_ids=(1, 2))
    host_fakes.add_slice("s2", ds_id, dashboard_ids=(2,))
    host_fakes.add_slice("s3", 999)  # unrelated dataset

    assert ds.usage_info(file_id) == {"datasources": 1, "charts": 2, "dashboards": 2}


def test_delete_datasources_for_file(tmp_path, host_fakes):
    ds, metadata, engine = _env(tmp_path)
    file_id = _seed_file(metadata, filename="b.xlsx", file_type="excel")
    ds.create_datasource(
        file_id=file_id, sheet_index=0, datasource_name="E0", created_by="u1", database_id=1
    )
    ds.create_datasource(
        file_id=file_id, sheet_index=1, datasource_name="E1", created_by="u1", database_id=1
    )

    assert ds.delete_datasources_for_file(file_id, deleted_by="u1", reason="user_deleted") == 2
    assert ds.list_for_file(file_id) == []
    assert host_fakes.tables() == []
    assert dbmod.get_session().query(FileDatasource).count() == 0

    assert ds.delete_datasources_for_file(file_id, deleted_by="u1", reason="user_deleted") == 0
