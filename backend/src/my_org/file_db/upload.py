"""Chunked resumable upload sessions (spec 5.5): validate, land, register."""

import json
import math
import os
import re
import shutil
import uuid
from pathlib import Path

from .config import (
    ALLOWED_EXTENSIONS,
    DUCKDB_NATIVE_ENCODINGS,
    FILENAME_MAX_LEN,
    UPLOAD_CHUNK_BYTES,
    UPLOAD_MAX_CSV_BYTES,
    UPLOAD_MAX_EXCEL_BYTES,
    UPLOAD_STATUS_ABORTED,
    UPLOAD_STATUS_COMPLETED,
    UPLOAD_STATUS_UPLOADING,
)
from .models import UploadSession
from .parsers import csv_parser

_FILENAME_RE = re.compile(r"^[A-Za-z0-9\u4e00-\u9fa5 ._\-()]+$")


class UploadManager:
    def __init__(self, storage, metadata):
        self.storage = storage
        self.metadata = metadata
        self.session = metadata.session

    def init_upload(
        self,
        created_by: str,
        filename: str,
        file_type: str,
        total_size: int,
        chunk_size: int = UPLOAD_CHUNK_BYTES,
    ) -> str:
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"unsupported file extension: {ext!r}")
        expected_type = "csv" if ext == ".csv" else "excel"
        if file_type != expected_type:
            raise ValueError(f"file_type {file_type!r} does not match extension {ext!r}")
        if len(filename) > FILENAME_MAX_LEN:
            raise ValueError(f"filename longer than {FILENAME_MAX_LEN} characters")
        if not _FILENAME_RE.match(filename):
            raise ValueError(f"filename contains unsupported characters: {filename!r}")
        max_size = UPLOAD_MAX_CSV_BYTES if file_type == "csv" else UPLOAD_MAX_EXCEL_BYTES
        if not isinstance(total_size, int) or total_size <= 0 or total_size > max_size:
            raise ValueError(f"total_size must be within (0, {max_size}] for {file_type}")
        if not isinstance(chunk_size, int) or chunk_size <= 0 or chunk_size > UPLOAD_CHUNK_BYTES:
            raise ValueError(f"chunk_size must be within (0, {UPLOAD_CHUNK_BYTES}]")

        upload_id = str(uuid.uuid4())
        self.session.add(
            UploadSession(
                id=upload_id,
                created_by=created_by,
                filename=filename,
                file_type=file_type,
                total_size=total_size,
                chunk_size=chunk_size,
                total_chunks=math.ceil(total_size / chunk_size),
                received_chunks="[]",
                status=UPLOAD_STATUS_UPLOADING,
            )
        )
        self._commit()
        return upload_id

    def add_chunk(self, upload_id: str, chunk_index: int, data: bytes) -> dict:
        up = self._get(upload_id)
        if chunk_index < 0 or chunk_index >= up.total_chunks:
            raise ValueError(f"chunk_index out of range: {chunk_index}")
        staging = Path(self.storage.staging_dir(up.created_by, upload_id))
        (staging / f"{chunk_index:06d}.part").write_bytes(data)
        received = sorted(set(json.loads(up.received_chunks)) | {chunk_index})
        up.received_chunks = json.dumps(received)
        self._commit()
        return self.get_status(upload_id)

    def get_status(self, upload_id: str) -> dict:
        up = self._get(upload_id)
        return {
            "upload_id": up.id,
            "filename": up.filename,
            "file_type": up.file_type,
            "total_size": up.total_size,
            "chunk_size": up.chunk_size,
            "total_chunks": up.total_chunks,
            "received_chunks": json.loads(up.received_chunks),
            "status": up.status,
        }

    def complete_upload(self, upload_id: str) -> str:
        up = self._get(upload_id)
        if up.status != UPLOAD_STATUS_UPLOADING:
            raise ValueError(f"upload {upload_id!r} already {up.status}")
        received = set(json.loads(up.received_chunks))
        missing = [i for i in range(up.total_chunks) if i not in received]
        if missing:
            raise ValueError(f"missing chunks: {missing}")

        staging = Path(self.storage.staging_dir(up.created_by, upload_id))
        merged = staging / "merged.tmp"
        with open(merged, "wb") as out:
            for i in range(up.total_chunks):
                with open(staging / f"{i:06d}.part", "rb") as part:
                    shutil.copyfileobj(part, out)

        file_id = str(uuid.uuid4())
        with open(merged, "rb") as f:
            storage_path = self.storage.save_file(f, up.created_by, file_id, up.filename)

        encoding = None
        delimiter = None
        if up.file_type == "csv":
            path = self.storage.get_file_path(storage_path)
            encoding = csv_parser.detect_encoding(path)
            if encoding not in DUCKDB_NATIVE_ENCODINGS:
                os.replace(csv_parser.transcode_to_utf8(path, encoding), path)
                encoding = "utf-8"
            delimiter = csv_parser.detect_delimiter(path, encoding)

        self.metadata.create_file_record(
            file_id=file_id,
            created_by=up.created_by,
            filename=up.filename,
            file_size=up.total_size,
            file_type=up.file_type,
            storage_path=storage_path,
            encoding=encoding,
            delimiter=delimiter,
        )
        self.storage.delete_staging(up.created_by, upload_id)
        up.status = UPLOAD_STATUS_COMPLETED
        self._commit()
        return file_id

    def abort_upload(self, upload_id: str) -> bool:
        up = self.session.get(UploadSession, upload_id)
        if up is None or up.status != UPLOAD_STATUS_UPLOADING:
            return False
        self.storage.delete_staging(up.created_by, upload_id)
        up.status = UPLOAD_STATUS_ABORTED
        self._commit()
        return True

    def _get(self, upload_id: str) -> UploadSession:
        up = self.session.get(UploadSession, upload_id)
        if up is None:
            raise KeyError(f"unknown upload: {upload_id!r}")
        return up

    def _commit(self) -> None:
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
