import importlib
import sys
import types

import pytest
import sqlalchemy.dialects


@pytest.fixture
def fake_superset(monkeypatch):
    base_mod = types.ModuleType("superset.db_engine_specs.base")

    class FakeBaseEngineSpec:
        pass

    base_mod.BaseEngineSpec = FakeBaseEngineSpec

    dbes_mod = types.ModuleType("superset.db_engine_specs")
    dbes_mod.base = base_mod
    dbes_mod.load_engine_specs = lambda: []

    monkeypatch.setitem(sys.modules, "superset", types.ModuleType("superset"))
    monkeypatch.setitem(sys.modules, "superset.db_engine_specs", dbes_mod)
    monkeypatch.setitem(sys.modules, "superset.db_engine_specs.base", base_mod)
    monkeypatch.setattr(sqlalchemy.dialects, "__all__", list(sqlalchemy.dialects.__all__))
    return dbes_mod


def test_engine_spec_attributes(fake_superset):
    module = importlib.import_module("my_org.file_db.db_engine_spec")
    spec = module.FileDBEngineSpec

    assert issubclass(spec, fake_superset.base.BaseEngineSpec)
    assert spec.engine == "filedb"
    assert spec.engine_name
    assert spec.default_driver == "duckdb"
    assert spec.sqlalchemy_uri_placeholder == "filedb://"
    assert spec.supports_file_upload is False
    assert spec.disable_ssh_tunneling is True


def test_register_wires_loader_and_dialect_scan(fake_superset):
    module = importlib.import_module("my_org.file_db.db_engine_spec")

    module.register()
    # dialect scan: /database/available builds its driver map from __all__
    assert "filedb" in sqlalchemy.dialects.__all__
    # engine spec discovery: load_engine_specs() must include ours
    specs = fake_superset.load_engine_specs()
    assert module.FileDBEngineSpec in specs

    module.register()  # idempotent
    specs = fake_superset.load_engine_specs()
    assert specs.count(module.FileDBEngineSpec) == 1
