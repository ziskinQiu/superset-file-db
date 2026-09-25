"""Constants and type maps for the file-db extension.

Every limit and enumeration here comes from the design spec
(docs/superpowers/specs/2026-09-25-file-database-engine-design.md).
"""

import os

UPLOAD_MAX_CSV_BYTES = 150 * 1024 * 1024
UPLOAD_MAX_EXCEL_BYTES = 500 * 1024 * 1024
FILE_EXPIRY_DAYS = 180
PREVIEW_ROW_LIMIT = 100
UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024
FILENAME_MAX_LEN = 255
EXPIRY_WARNING_DAYS = 7
CLEANUP_THROTTLE_SECONDS = 3600

COLUMN_TYPES = {"string", "integer", "float", "datetime", "boolean"}

# user-facing type -> DuckDB type used in CREATE VIEW casts
DUCKDB_TYPE_MAP = {
    "string": "VARCHAR",
    "integer": "BIGINT",
    "float": "DOUBLE",
    "datetime": "TIMESTAMP",
    "boolean": "BOOLEAN",
}

# user-facing type -> SQLAlchemy type *name* returned by the dialect
SQLALCHEMY_TYPE_NAMES = {
    "string": "VARCHAR",
    "integer": "BIGINT",
    "float": "FLOAT",
    "datetime": "TIMESTAMP",
    "boolean": "BOOLEAN",
}

DELIMITERS = {",", ";", "\t", "|", " "}
ENCODINGS = ["utf-8", "gbk", "gb2312", "latin-1"]
ALLOWED_EXTENSIONS = {".csv", ".xls", ".xlsx"}

# encodings DuckDB read_csv understands natively; anything else is
# transcoded to UTF-8 at upload-complete time
DUCKDB_NATIVE_ENCODINGS = {"utf-8", "utf-16", "latin-1"}

# storage root configured by the admin (spec 5.2)
UPLOAD_ROOT = os.environ.get("FILE_DB_UPLOAD_ROOT", "/data/uploads")

VIEW_PREFIX = "file_"
STAGING_DIR_NAME = ".staging"
PARQUET_DIR_NAME = "parquet"

FILE_STATUS_ACTIVE = "active"
FILE_STATUS_EXPIRED = "expired"
FILE_STATUS_DELETED = "deleted"

UPLOAD_STATUS_UPLOADING = "uploading"
UPLOAD_STATUS_COMPLETED = "completed"
UPLOAD_STATUS_ABORTED = "aborted"

DELETE_REASON_USER = "user_deleted"
DELETE_REASON_ADMIN = "admin_deleted"
DELETE_REASON_EXPIRED = "expired"
