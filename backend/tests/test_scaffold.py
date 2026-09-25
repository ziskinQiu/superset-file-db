import my_org.file_db.config as cfg


def test_package_imports():
    import my_org.file_db  # noqa: F401


def test_limits_match_spec():
    assert cfg.UPLOAD_MAX_CSV_BYTES == 150 * 1024 * 1024
    assert cfg.UPLOAD_MAX_EXCEL_BYTES == 500 * 1024 * 1024
    assert cfg.FILE_EXPIRY_DAYS == 180
    assert cfg.PREVIEW_ROW_LIMIT == 100
    assert cfg.UPLOAD_CHUNK_BYTES == 8 * 1024 * 1024
    assert cfg.FILENAME_MAX_LEN == 255
    assert cfg.EXPIRY_WARNING_DAYS == 7


def test_type_maps_are_consistent():
    assert cfg.COLUMN_TYPES == {"string", "integer", "float", "datetime", "boolean"}
    assert set(cfg.DUCKDB_TYPE_MAP) == cfg.COLUMN_TYPES
    assert set(cfg.SQLALCHEMY_TYPE_NAMES) == cfg.COLUMN_TYPES


def test_upload_and_encoding_options():
    assert cfg.DELIMITERS == {",", ";", "\t", "|", " "}
    assert cfg.ENCODINGS == ["utf-8", "gbk", "gb2312", "latin-1"]
    assert cfg.ALLOWED_EXTENSIONS == {".csv", ".xls", ".xlsx"}


def test_entrypoint_registers_dialect():
    from my_org.file_db.entrypoint import register_extension
    from sqlalchemy.dialects import registry

    register_extension()
    # SQLAlchemy 1.4 PluginLoader stores plugins in `impls` (no `registry` attr)
    assert "filedb" in registry.impls


def test_entrypoint_installs_engine_factory():
    # Superset-side queries (test_connection pre-ping, SQL Lab) hit the dialect
    # before any extension API request — the factory must be installed eagerly.
    import my_org.file_db.entrypoint  # noqa: F401
    from my_org.file_db import dialect, services

    class FakeCursor:
        description = None
        rowcount = -1

        def execute(self, sql, params=None):
            return self

        def fetchall(self):
            return [(1,)]

        def close(self):
            pass

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    class FakeEngine:
        def get_connection(self):
            return FakeConnection()

        def ensure_view_by_name(self, name):
            return name

    previous = services._engine
    services._engine = FakeEngine()
    try:
        cursor = dialect.FileDBModule.connect().cursor()
        cursor.execute("SELECT 1")
        assert cursor.fetchall() == [(1,)]
    finally:
        services._engine = previous
