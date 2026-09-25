import io
from pathlib import Path

import pytest

from my_org.file_db.storage.local import LocalStorageBackend


@pytest.fixture
def storage(tmp_path):
    return LocalStorageBackend(base_path=str(tmp_path))


def test_save_file_layout_and_roundtrip(storage, tmp_path):
    rel = storage.save_file(io.BytesIO(b"hello"), "u1", "f1", "a.csv")
    assert rel == "u1/f1/a.csv"
    assert (tmp_path / "u1" / "f1" / "a.csv").read_bytes() == b"hello"
    assert Path(storage.get_file_path(rel)).read_bytes() == b"hello"


def test_delete_file_and_dir(storage):
    storage.save_file(io.BytesIO(b"one"), "u1", "f1", "a.csv")
    storage.save_file(io.BytesIO(b"two"), "u1", "f1", "b.csv")
    assert storage.delete_file("u1/f1/a.csv") is True
    assert storage.delete_file("u1/f1") is True
    assert storage.delete_file("u1/f1") is False


def test_file_exists(storage):
    storage.save_file(io.BytesIO(b"x"), "u1", "f1", "a.csv")
    assert storage.file_exists("u1/f1/a.csv") is True
    assert storage.file_exists("u1/f1/b.csv") is False


def test_path_traversal_rejected(storage):
    with pytest.raises(ValueError):
        storage.get_file_path("../../etc/passwd")
    with pytest.raises(ValueError):
        storage.delete_file("u1/../../x")
    with pytest.raises(ValueError):
        storage.file_exists("../x")


def test_staging_dir_lifecycle(storage, tmp_path):
    p = storage.staging_dir("u1", "up1")
    assert Path(p).is_dir()
    assert Path(p) == tmp_path / ".staging" / "u1" / "up1"
    assert storage.delete_staging("u1", "up1") is True
    assert not Path(p).exists()


def test_user_isolation(storage, tmp_path):
    storage.save_file(io.BytesIO(b"one"), "u1", "f1", "a.csv")
    storage.save_file(io.BytesIO(b"two"), "u2", "f1", "a.csv")
    storage.save_file(io.BytesIO(b"three"), "u1", "f2", "a.csv")
    assert (tmp_path / "u1" / "f1" / "a.csv").read_bytes() == b"one"
    assert (tmp_path / "u2" / "f1" / "a.csv").read_bytes() == b"two"
    assert (tmp_path / "u1" / "f2" / "a.csv").read_bytes() == b"three"
