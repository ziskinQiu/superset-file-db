"""UploadService: chunked upload orchestration + eager schema registration."""

import csv

from ..config import UPLOAD_CHUNK_BYTES
from ..parsers import csv_parser, excel_parser


class UploadService:
    def __init__(self, upload, storage, metadata):
        self.upload = upload
        self.storage = storage
        self.metadata = metadata

    def init(self, user_id: str, payload: dict) -> dict:
        for key in ("filename", "file_type", "total_size"):
            if key not in payload:
                raise ValueError(f"missing required field: {key}")
        upload_id = self.upload.init_upload(
            created_by=user_id,
            filename=payload["filename"],
            file_type=payload["file_type"],
            total_size=payload["total_size"],
            chunk_size=payload.get("chunk_size", UPLOAD_CHUNK_BYTES),
        )
        status = self.upload.get_status(upload_id)
        return {
            "upload_id": upload_id,
            "chunk_size": status["chunk_size"],
            "total_chunks": status["total_chunks"],
        }

    def chunk(self, user_id: str, upload_id: str, index: int, data: bytes) -> dict:
        return self.upload.add_chunk(upload_id, index, data)

    def complete(self, user_id: str, upload_id: str) -> dict:
        file_id = self.upload.complete_upload(upload_id)
        self._register_schema(self.metadata.get_file(file_id))
        return {"file_id": file_id}

    def abort(self, user_id: str, upload_id: str) -> dict:
        if not self.upload.abort_upload(upload_id):
            raise KeyError(f"unknown upload: {upload_id!r}")
        return self.upload.get_status(upload_id)

    def status(self, user_id: str, upload_id: str) -> dict:
        return self.upload.get_status(upload_id)

    def _register_schema(self, record) -> None:
        """Parse schema eagerly so datasources can be created right away (spec 5.10)."""
        path = self.storage.get_file_path(record.storage_path)
        try:
            if record.file_type == "csv":
                schema = csv_parser.parse_schema(path, record.encoding, record.delimiter)
                self.metadata.create_columns(record.id, schema.columns)
                record.row_count = csv_parser.count_rows(path, record.encoding, record.delimiter)
                record.column_count = len(schema.columns)
            else:
                sheets = excel_parser.list_sheets(path)
                sheet_ids = self.metadata.create_sheets(record.id, sheets)
                for sheet, sheet_id in zip(sheets, sheet_ids):
                    columns = excel_parser.parse_schema(path, sheet.index).columns
                    self.metadata.create_columns(record.id, columns, sheet_id=sheet_id)
                record.sheet_count = len(sheets)
                record.row_count = sum(s.row_count or 0 for s in sheets)
        except (UnicodeDecodeError, csv.Error) as exc:
            raise ValueError(f"cannot parse file: {exc}") from exc
        self.metadata.session.commit()
