"""Superset DB engine spec for the `filedb` dialect (host-only glue).

Makes the file database show up in Superset's "Supported databases" list and
lets `Database.db_engine_spec` resolve to it. `.supx` deployments do not run
`pip install`, so entry points are not discovered at runtime — `register()`
wires the spec in explicitly, mirroring the dialect registration in entrypoint.
"""

import sqlalchemy.dialects

from superset.db_engine_specs.base import BaseEngineSpec


class FileDBEngineSpec(BaseEngineSpec):
    engine = "filedb"
    engine_name = "File Database"
    default_driver = "duckdb"
    sqlalchemy_uri_placeholder = "filedb://"
    disable_ssh_tunneling = True
    supports_file_upload = False


def register() -> None:
    """Wire FileDBEngineSpec into the host's engine discovery (idempotent)."""
    # 1) the native dialect scan in get_available_engine_specs() iterates
    #    sqlalchemy.dialects.__all__ — make it see our runtime-registered dialect
    if "filedb" not in sqlalchemy.dialects.__all__:
        sqlalchemy.dialects.__all__ = [*sqlalchemy.dialects.__all__, "filedb"]

    # 2) engine specs load from built-in modules + entry points only — wrap the
    #    loader so ours is discoverable without an installed distribution
    import superset.db_engine_specs as db_engine_specs

    if getattr(db_engine_specs.load_engine_specs, "_file_db_registered", False):
        return
    original = db_engine_specs.load_engine_specs

    def load_engine_specs_with_file_db():
        specs = list(original())
        if not any(getattr(spec, "engine", None) == "filedb" for spec in specs):
            specs.append(FileDBEngineSpec)
        return specs

    load_engine_specs_with_file_db._file_db_registered = True
    db_engine_specs.load_engine_specs = load_engine_specs_with_file_db
