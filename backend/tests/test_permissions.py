from types import SimpleNamespace

import pytest
from flask import Flask

from my_org.file_db import host_db, permissions


def _user(uid="u1", roles=(), perms=()):
    return SimpleNamespace(
        id=uid,
        username=f"user-{uid}",
        roles=[SimpleNamespace(name=name) for name in roles],
        permissions=set(perms),
        is_anonymous=False,
    )


class _File:
    def __init__(self, created_by="u1"):
        self.created_by = created_by


def test_owner_passes_other_denied():
    record = _File(created_by="u1")
    permissions.check_file_owner(record, _user("u1"))  # owner passes

    with pytest.raises(PermissionError):
        permissions.check_file_owner(record, _user("u2"))


def test_admin_bypasses_owner_check():
    record = _File(created_by="u1")
    permissions.check_file_owner(record, _user("root", roles=["Admin"]))
    assert permissions.is_admin(_user("root", roles=["Admin"])) is True
    assert permissions.is_admin(_user("u2", roles=["Gamma"])) is False


def test_can_create_datasource():
    assert permissions.can_create_datasource(_user("root", roles=["Admin"])) is True
    assert (
        permissions.can_create_datasource(_user("u2", roles=["Alpha"], perms={"can_write on Dataset"}))
        is True
    )
    assert permissions.can_create_datasource(_user("u3", roles=["Gamma"])) is False


def test_unauthenticated_raises():
    app = Flask(__name__)
    with app.test_request_context():  # logged-out request
        with pytest.raises(PermissionError):
            permissions.current_user()
        with pytest.raises(PermissionError):
            permissions.current_user_id()

    with pytest.raises(PermissionError):  # outside any app context
        permissions.current_user()
    with pytest.raises(PermissionError):
        permissions.check_file_owner(_File())


def test_host_db_lazy():
    host_db.set_injectables(metadata_uri=None, session_factory=None, models={})
    with pytest.raises(RuntimeError):
        host_db.resolve_model("SqlaTable")  # no superset package available
    with pytest.raises(RuntimeError):
        host_db.get_superset_session_factory()

    class FakeTable:
        pass

    host_db.set_injectables(
        metadata_uri="sqlite://", session_factory=lambda: "session", models={"SqlaTable": FakeTable}
    )
    assert host_db.resolve_model("SqlaTable") is FakeTable
    assert host_db.get_superset_session_factory()() == "session"
    assert host_db.get_metadata_db_uri() == "sqlite://"

    host_db.set_injectables(metadata_uri=None, session_factory=None, models={})
