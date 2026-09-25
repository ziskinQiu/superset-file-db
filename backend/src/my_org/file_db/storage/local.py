"""Local filesystem storage backend (spec 3.1.2).

Layout: <base>/<user_id>/<file_id>/<filename>
Staging: <base>/.staging/<user_id>/<upload_id>/
"""

import shutil
from pathlib import Path
from typing import BinaryIO

from .. import config
from .base import StorageBackend


class LocalStorageBackend(StorageBackend):
    def __init__(self, base_path: str = config.UPLOAD_ROOT):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def save_file(self, file_data: BinaryIO, user_id: str, file_id: str, filename: str) -> str:
        rel = str(Path(user_id) / file_id / filename)
        target = self._resolve_safe(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as f:
            shutil.copyfileobj(file_data, f)
        return rel

    def get_file_path(self, storage_path: str) -> str:
        return str(self._resolve_safe(storage_path))

    def delete_file(self, storage_path: str) -> bool:
        target = self._resolve_safe(storage_path)
        if not target.exists():
            return False
        if target.is_file():
            target.unlink()
        else:
            shutil.rmtree(target)
        return True

    def file_exists(self, storage_path: str) -> bool:
        return self._resolve_safe(storage_path).exists()

    def staging_dir(self, user_id: str, upload_id: str) -> str:
        path = self._resolve_safe(str(Path(config.STAGING_DIR_NAME) / user_id / upload_id))
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def delete_staging(self, user_id: str, upload_id: str) -> bool:
        return self.delete_file(str(Path(config.STAGING_DIR_NAME) / user_id / upload_id))

    def _resolve_safe(self, storage_path: str) -> Path:
        base = self.base_path.resolve()
        target = (self.base_path / storage_path).resolve()
        if target != base and base in target.parents:
            return target
        raise ValueError(f"storage_path escapes storage root: {storage_path!r}")
