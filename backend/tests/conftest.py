"""Shared fixtures: a fake Superset host (models + session) injected into host_db."""

import pytest

from my_org.file_db import host_db


class FakeSqlaTable:
    def __init__(self):
        self.id = None
        self.table_name = None
        self.database_id = None
        self.description = None
        self.metadata_fetched = False

    def fetch_metadata(self):
        self.metadata_fetched = True


class FakeDatabase:
    def __init__(self, id, database_name, sqlalchemy_uri):
        self.id = id
        self.database_name = database_name
        self.sqlalchemy_uri = sqlalchemy_uri


class FakeSlice:
    def __init__(self, id, datasource_id, dashboards=()):
        self.id = id
        self.datasource_id = datasource_id
        self.dashboards = list(dashboards)


class FakeDashboard:
    def __init__(self, id):
        self.id = id


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows

    def filter_by(self, **kw):
        return FakeQuery(
            [r for r in self.rows if all(getattr(r, k, None) == v for k, v in kw.items())]
        )

    def one_or_none(self):
        return self.rows[0] if self.rows else None


class FakeHostSession:
    def __init__(self):
        self.store = {}
        self._next_id = 100

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = self._next_id
            self._next_id += 1
        self.store.setdefault(type(obj), {})[obj.id] = obj

    def commit(self):
        pass

    def rollback(self):
        pass

    def delete(self, obj):
        self.store.get(type(obj), {}).pop(obj.id, None)

    def get(self, model, obj_id):
        return self.store.get(model, {}).get(obj_id)

    def query(self, model):
        return FakeQuery(list(self.store.get(model, {}).values()))


class FakeHost:
    def __init__(self):
        self.session = FakeHostSession()

    def add_database(self, database_name, sqlalchemy_uri, id=None):
        db = FakeDatabase(id, database_name, sqlalchemy_uri)
        self.session.add(db)
        return db

    def add_slice(self, slice_id, datasource_id, dashboard_ids=()):
        s = FakeSlice(
            slice_id, datasource_id, [FakeDashboard(d) for d in dashboard_ids]
        )
        self.session.add(s)
        return s

    def tables(self):
        return list(self.session.store.get(FakeSqlaTable, {}).values())


@pytest.fixture
def host_fakes():
    fake = FakeHost()
    host_db.set_injectables(
        models={"SqlaTable": FakeSqlaTable, "Database": FakeDatabase, "Slice": FakeSlice},
        session_factory=lambda: fake.session,
    )
    yield fake
    host_db.set_injectables(metadata_uri=None, session_factory=None, models={})
