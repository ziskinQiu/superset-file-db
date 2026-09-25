import json
from types import SimpleNamespace

import pytest
from flask import Flask

import superset_core.rest_api.decorators as decorators
from my_org.file_db import permissions

REGISTERED = {}


def _fake_api(id, name, description=None, resource_name=None):
    def deco(cls):
        REGISTERED[id] = cls
        return cls

    return deco


def _recorder(calls, name):
    def f(*args, **kwargs):
        calls.append((name, args, kwargs))
        return {"ok": name}

    return f


def _fake_services(calls):
    return SimpleNamespace(
        upload=SimpleNamespace(
            init=_recorder(calls, "upload.init"),
            chunk=_recorder(calls, "upload.chunk"),
            complete=_recorder(calls, "upload.complete"),
            abort=_recorder(calls, "upload.abort"),
            status=_recorder(calls, "upload.status"),
        ),
        files=SimpleNamespace(
            list=_recorder(calls, "files.list"),
            get=_recorder(calls, "files.get"),
            preview=_recorder(calls, "files.preview"),
            save_config=_recorder(calls, "files.save_config"),
            usage=_recorder(calls, "files.usage"),
            delete=_recorder(calls, "files.delete"),
            notifications=_recorder(calls, "files.notifications"),
        ),
        columns=SimpleNamespace(
            list=_recorder(calls, "columns.list"),
            update=_recorder(calls, "columns.update"),
            import_config=_recorder(calls, "columns.import_config"),
            history=_recorder(calls, "columns.history"),
        ),
        datasources=SimpleNamespace(
            connections=_recorder(calls, "datasources.connections"),
            create=_recorder(calls, "datasources.create"),
            list_for_file=_recorder(calls, "datasources.list_for_file"),
            cleanup=_recorder(calls, "datasources.cleanup"),
        ),
    )


@pytest.fixture
def ns(monkeypatch):
    monkeypatch.setattr(decorators, "api", _fake_api)
    calls = []
    services = _fake_services(calls)

    import my_org.file_db.api.columns_api as columns_api
    import my_org.file_db.api.datasources_api as datasources_api
    import my_org.file_db.api.files_api as files_api

    for module in (files_api, columns_api, datasources_api):
        monkeypatch.setattr(module, "get_services", lambda: services)
    monkeypatch.setattr(
        permissions,
        "current_user",
        lambda: SimpleNamespace(
            id="u1", username="user-u1", roles=[], permissions=set(), is_anonymous=False
        ),
    )
    return SimpleNamespace(
        app=_app(),
        calls=calls,
        services=services,
        files=files_api.FilesApi(),
        columns=columns_api.ColumnsApi(),
        datasources=datasources_api.DatasourcesApi(),
    )


def _app():
    app = Flask(__name__)
    # stub FAB security manager: treat resources as public in unit tests
    app.appbuilder = SimpleNamespace(
        sm=SimpleNamespace(is_item_public=lambda *args, **kwargs: True)
    )
    return app


def _call(ns, fn, *args, path="/", json_body=None, method="GET"):
    kwargs = {"method": method}
    if json_body is not None:
        kwargs["data"] = json.dumps(json_body)
        kwargs["content_type"] = "application/json"
    with ns.app.test_request_context(path, **kwargs):
        return fn(*args)


def test_files_endpoints(ns):
    assert _call(ns, ns.files.get_files).status_code == 200
    assert ns.calls[-1] == ("files.list", ("u1",), {})

    assert _call(ns, ns.files.get_file, "f1").status_code == 200
    assert ns.calls[-1] == ("files.get", ("u1", "f1"), {})

    resp = _call(ns, ns.files.preview_file, "f1", path="/?sheet_index=2")
    assert resp.get_json()["result"] == {"ok": "files.preview"}
    assert ns.calls[-1] == ("files.preview", ("u1", "f1", 2), {})

    body = {"datasource_name": "Sales"}
    assert _call(ns, ns.files.save_file_config, "f1", json_body=body, method="PUT").status_code == 200
    assert ns.calls[-1] == ("files.save_config", ("u1", "f1", body), {})

    assert _call(ns, ns.files.file_usage, "f1").status_code == 200
    assert ns.calls[-1] == ("files.usage", ("u1", "f1"), {})

    assert _call(ns, ns.files.delete_file, "f1", method="DELETE").status_code == 200
    assert ns.calls[-1] == ("files.delete", ("u1", "f1"), {})

    assert _call(ns, ns.files.get_notifications).status_code == 200
    assert ns.calls[-1] == ("files.notifications", ("u1",), {})


def test_upload_endpoints(ns):
    body = {"filename": "a.csv", "file_type": "csv", "total_size": 10}
    assert _call(ns, ns.files.init_upload, json_body=body, method="POST").status_code == 200
    assert ns.calls[-1] == ("upload.init", ("u1", body), {})

    with ns.app.test_request_context(
        data=b"\x00abc", content_type="application/octet-stream", method="PUT"
    ):
        resp = ns.files.upload_chunk("up1", 2)
    assert resp.status_code == 200
    assert ns.calls[-1] == ("upload.chunk", ("u1", "up1", 2, b"\x00abc"), {})

    assert _call(ns, ns.files.complete_upload, "up1", method="POST").status_code == 200
    assert ns.calls[-1] == ("upload.complete", ("u1", "up1"), {})

    assert _call(ns, ns.files.abort_upload, "up1", method="POST").status_code == 200
    assert ns.calls[-1] == ("upload.abort", ("u1", "up1"), {})

    assert _call(ns, ns.files.upload_status, "up1").status_code == 200
    assert ns.calls[-1] == ("upload.status", ("u1", "up1"), {})


def test_columns_endpoints(ns):
    assert _call(ns, ns.columns.get_columns, "f1", path="/?sheet_id=s1").status_code == 200
    assert ns.calls[-1] == ("columns.list", ("u1", "f1", "s1"), {})

    body = {"type": "float", "format": None}
    assert _call(ns, ns.columns.update_column, "f1", "c1", json_body=body, method="PUT").status_code == 200
    assert ns.calls[-1] == ("columns.update", ("u1", "f1", "c1", "float", None), {})

    config = {"columns": [{"name": "a", "type": "float"}]}
    assert _call(ns, ns.columns.import_columns, "f1", json_body=config, method="POST").status_code == 200
    assert ns.calls[-1] == ("columns.import_config", ("u1", "f1", config), {})

    assert _call(ns, ns.columns.column_history, "f1").status_code == 200
    assert ns.calls[-1] == ("columns.history", ("u1", "f1"), {})


def test_datasources_endpoints(ns):
    assert _call(ns, ns.datasources.get_connections).status_code == 200
    assert ns.calls[-1] == ("datasources.connections", ("u1",), {})

    body = {
        "file_id": "f1",
        "sheet_indices": [0, 1],
        "name": "Sales",
        "description": "d",
        "database_id": 3,
    }
    assert _call(ns, ns.datasources.create_datasources, json_body=body, method="POST").status_code == 200
    assert ns.calls[-1] == ("datasources.create", ("u1", "f1", [0, 1], "Sales", "d", 3), {})

    assert _call(ns, ns.datasources.file_datasources, "f1").status_code == 200
    assert ns.calls[-1] == ("datasources.list_for_file", ("u1", "f1"), {})

    assert _call(ns, ns.datasources.run_cleanup, json_body={"force": True}, method="POST").status_code == 200
    assert ns.calls[-1] == ("datasources.cleanup", ("u1", True), {})


def test_error_mapping(ns):
    def raiser(exc):
        def f(*args, **kwargs):
            raise exc

        return f

    cases = [
        (PermissionError("denied"), 403),
        (ValueError("bad input"), 400),
        (KeyError("missing"), 404),
        (RuntimeError("boom"), 500),
    ]
    for exc, status in cases:
        ns.services.files.list = raiser(exc)
        assert _call(ns, ns.files.get_files).status_code == status


def test_api_registration_smoke():
    assert set(REGISTERED) >= {
        "file_db_files_api",
        "file_db_columns_api",
        "file_db_datasources_api",
    }
