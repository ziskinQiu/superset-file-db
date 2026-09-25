"""Extension entrypoint: registers REST APIs and the filedb dialect."""

from sqlalchemy.dialects import registry


def register_extension() -> None:
    # .supx deployments do not run `pip install`, so the pyproject
    # entry-point is not discovered at runtime. Register explicitly.
    registry.register("filedb", "my_org.file_db.dialect", "FileDBDialect")


register_extension()

# Install the shared query engine factory eagerly: Superset-side queries
# (test_connection pre-ping, SQL Lab) touch the dialect before any extension
# API request has built the service graph. The factory itself stays lazy.
from . import dialect as _dialect  # noqa: E402
from .services import get_engine as _get_engine  # noqa: E402

_dialect.set_engine_factory(_get_engine)

# Register the Superset DB engine spec so `filedb` appears in the
# "Supported databases" list. Host-only glue: superset is absent in unit tests.
try:
    from . import db_engine_spec

    db_engine_spec.register()
except ImportError:
    pass

# Importing API modules registers them with the Superset host via @api.
# The host replaces the @api decorator before loading extensions; outside the
# host (unit tests) the stub raises NotImplementedError, which is fine to skip.
try:
    from .api import columns_api, datasources_api, files_api  # noqa: E402,F401
except NotImplementedError:
    pass

print("file-db extension registered")
