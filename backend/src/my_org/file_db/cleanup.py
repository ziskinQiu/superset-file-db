"""Expiry cleanup with one cascade path for deletion (spec 5.12/5.13)."""

import logging
import shutil
import time
from datetime import timedelta
from pathlib import Path

from .config import (
    CLEANUP_THROTTLE_SECONDS,
    DELETE_REASON_ADMIN,
    DELETE_REASON_EXPIRED,
    EXPIRY_WARNING_DAYS,
    FILE_STATUS_ACTIVE,
    FILE_STATUS_EXPIRED,
)
from .models import UploadedFile, _utcnow

logger = logging.getLogger(__name__)

_last_run = 0.0


class CleanupManager:
    def __init__(self, storage, metadata, datasource, query_engine):
        self.storage = storage
        self.metadata = metadata
        self.datasource = datasource
        self.query_engine = query_engine

    def delete_file_cascade(self, file_id: str, reason: str, deleted_by: str) -> bool:
        """Single cascade entry point; each step tolerates failures (spec 5.12 order)."""
        record = self.metadata.get_file(file_id)
        if record is None:
            return False
        filename, storage_path = record.filename, record.storage_path

        steps = [
            lambda: self.datasource.delete_datasources_for_file(file_id, deleted_by, reason),
            lambda: self.query_engine.invalidate(file_id),
            lambda: self._drop_parquet(file_id),
            lambda: self.storage.delete_file(storage_path),
            lambda: self.metadata.delete_file_record(file_id),
        ]
        for step in steps:
            try:
                step()
            except Exception:
                logger.exception("cleanup step failed for file %s", file_id)

        self.metadata.log_delete(file_id, filename, reason, deleted_by)  # kept forever
        return True

    def expire_due_files(self, now=None) -> list[str]:
        now = now or _utcnow()
        due = (
            self.metadata.session.query(UploadedFile)
            .filter(
                UploadedFile.status.in_([FILE_STATUS_ACTIVE, FILE_STATUS_EXPIRED]),
                UploadedFile.expiry_time < now,
            )
            .all()
        )
        return [
            record.id
            for record in due
            if self.delete_file_cascade(record.id, DELETE_REASON_EXPIRED, deleted_by="system")
        ]

    def manual_delete_file(self, file_id: str, deleted_by: str) -> bool:
        return self.delete_file_cascade(file_id, DELETE_REASON_ADMIN, deleted_by)

    def upcoming_expiries(self, user_id: str | None = None, days: int = EXPIRY_WARNING_DAYS):
        now = _utcnow()
        query = self.metadata.session.query(UploadedFile).filter(
            UploadedFile.status == FILE_STATUS_ACTIVE,
            UploadedFile.expiry_time >= now,
            UploadedFile.expiry_time <= now + timedelta(days=days),
        )
        if user_id is not None:
            query = query.filter(UploadedFile.created_by == user_id)
        return query.order_by(UploadedFile.expiry_time).all()

    def run_auto_cleanup(self, force: bool = False) -> list[str]:
        """Throttled auto cleanup (spec 5.13: auto-first, admin manual as backup)."""
        global _last_run
        now = time.time()
        if not force and now - _last_run < CLEANUP_THROTTLE_SECONDS:
            return []
        _last_run = now
        return self.expire_due_files()

    def _drop_parquet(self, file_id: str) -> None:
        shutil.rmtree(Path(self.query_engine.parquet_dir) / file_id, ignore_errors=True)
