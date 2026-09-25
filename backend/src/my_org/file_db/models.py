"""ORM models for file metadata, upload sessions and audit logs.

Audit tables (column_type_change_logs, file_delete_logs) are append-only
and never purged, per spec 5.9/5.12.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from .db import Base


def _uuid_pk():
    return Column(String(36), primary_key=True)


def _utcnow():
    # naive UTC to match DateTime columns and caller-supplied datetimes
    return datetime.now(timezone.utc).replace(tzinfo=None)


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id = _uuid_pk()
    created_by = Column(String(36), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    file_type = Column(String(16), nullable=False)  # 'csv' | 'excel'
    storage_path = Column(String(500), nullable=False)
    upload_time = Column(DateTime, nullable=False)
    expiry_time = Column(DateTime, nullable=False)
    status = Column(String(16), nullable=False, default="active")
    sheet_count = Column(Integer, nullable=False, default=1)
    row_count = Column(BigInteger, nullable=True)
    column_count = Column(Integer, nullable=True)
    encoding = Column(String(32), nullable=True)
    delimiter = Column(String(8), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    columns = relationship(
        "FileColumn",
        back_populates="file",
        cascade="all, delete-orphan",
        order_by="FileColumn.column_order",
    )
    sheets = relationship(
        "FileSheet",
        back_populates="file",
        cascade="all, delete-orphan",
        order_by="FileSheet.sheet_index",
    )


class FileSheet(Base):
    __tablename__ = "file_sheets"

    id = _uuid_pk()
    file_id = Column(String(36), ForeignKey("uploaded_files.id", ondelete="CASCADE"), nullable=False, index=True)
    sheet_name = Column(String(255), nullable=False)
    sheet_index = Column(Integer, nullable=False)
    row_count = Column(BigInteger, nullable=True)
    column_count = Column(Integer, nullable=True)
    is_selected = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    file = relationship("UploadedFile", back_populates="sheets")


class FileColumn(Base):
    __tablename__ = "file_columns"

    id = _uuid_pk()
    file_id = Column(String(36), ForeignKey("uploaded_files.id", ondelete="CASCADE"), nullable=False, index=True)
    sheet_id = Column(String(36), ForeignKey("file_sheets.id", ondelete="CASCADE"), nullable=True, index=True)
    column_name = Column(String(255), nullable=False)
    column_type = Column(String(50), nullable=False)
    column_format = Column(String(100), nullable=True)
    column_order = Column(Integer, nullable=False)
    is_nullable = Column(Boolean, nullable=False, default=True)
    sample_values = Column(Text, nullable=False, default="[]")
    is_user_defined = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    file = relationship("UploadedFile", back_populates="columns")


class UploadSession(Base):
    __tablename__ = "upload_sessions"

    id = _uuid_pk()
    created_by = Column(String(36), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(16), nullable=False)
    total_size = Column(BigInteger, nullable=False)
    chunk_size = Column(Integer, nullable=False)
    total_chunks = Column(Integer, nullable=False)
    received_chunks = Column(Text, nullable=False, default="[]")
    status = Column(String(16), nullable=False, default="uploading")
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class ColumnTypeChangeLog(Base):
    __tablename__ = "column_type_change_logs"

    id = _uuid_pk()
    file_id = Column(String(36), nullable=False, index=True)
    column_id = Column(String(36), nullable=False)
    column_name = Column(String(255), nullable=False)
    old_type = Column(String(50), nullable=False)
    new_type = Column(String(50), nullable=False)
    old_format = Column(String(100), nullable=True)
    new_format = Column(String(100), nullable=True)
    changed_by = Column(String(36), nullable=False)
    changed_at = Column(DateTime, nullable=False)


class FileDeleteLog(Base):
    __tablename__ = "file_delete_logs"

    id = _uuid_pk()
    file_id = Column(String(36), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    deleted_at = Column(DateTime, nullable=False)
    reason = Column(String(32), nullable=False)
    deleted_by = Column(String(36), nullable=False)


class FileDatasource(Base):
    __tablename__ = "file_datasources"

    id = _uuid_pk()
    file_id = Column(String(36), nullable=False, index=True)
    sheet_id = Column(String(36), nullable=True)
    datasource_id = Column(Integer, nullable=False)
    datasource_name = Column(String(255), nullable=False)
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
