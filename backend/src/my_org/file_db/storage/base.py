"""Storage backend abstraction (spec 3.1.1)."""

from abc import ABC, abstractmethod
from typing import BinaryIO


class StorageBackend(ABC):
    @abstractmethod
    def save_file(self, file_data: BinaryIO, user_id: str, file_id: str, filename: str) -> str:
        """Persist file_data and return its storage_path (relative to the backend root)."""

    @abstractmethod
    def get_file_path(self, storage_path: str) -> str:
        """Absolute local path for a stored file."""

    @abstractmethod
    def delete_file(self, storage_path: str) -> bool:
        """Delete a stored file (or file directory); False when absent."""

    @abstractmethod
    def file_exists(self, storage_path: str) -> bool:
        """Whether the stored file exists."""

    @abstractmethod
    def staging_dir(self, user_id: str, upload_id: str) -> str:
        """Ensure and return the chunk staging directory for an upload session."""

    @abstractmethod
    def delete_staging(self, user_id: str, upload_id: str) -> bool:
        """Remove the staging directory; False when absent."""
