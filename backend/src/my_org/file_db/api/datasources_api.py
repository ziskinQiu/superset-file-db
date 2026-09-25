"""Datasource and admin cleanup endpoints."""

from flask import Response, request
from flask_appbuilder.api import expose, protect, safe
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from .. import permissions
from . import error_response, get_services


@api(
    id="file_db_datasources_api",
    name="File DB Datasources API",
    description="Create datasets and run cleanup",
)
class DatasourcesApi(RestApi):
    openapi_spec_tag = "File DB Datasources"
    class_permission_name = "file_db_datasources"

    @expose("/datasources/connections", methods=("GET",))
    @protect()
    @safe
    def get_connections(self) -> Response:
        """List available 'File Database' connections.

        ---
        get:
            description: List available 'File Database' connections.
            responses:
                200:
                    description: Connection list
                401:
                    $ref: '#/components/responses/401'
        """
        try:
            result = get_services().datasources.connections(permissions.current_user_id())
            return self.response(200, result=result)
        except Exception as exc:
            return error_response(exc)

    @expose("/datasources", methods=("POST",))
    @protect()
    @safe
    def create_datasources(self) -> Response:
        """Create datasets for a file (one per selected sheet).

        ---
        post:
            description: Create datasets for a file (one per selected sheet).
            responses:
                200:
                    description: Created datasets
                401:
                    $ref: '#/components/responses/401'
        """
        try:
            body = request.get_json(force=True) or {}
            result = get_services().datasources.create(
                permissions.current_user_id(),
                body.get("file_id"),
                body.get("sheet_indices") or [],
                body.get("name"),
                body.get("description"),
                body.get("database_id"),
            )
            return self.response(200, result=result)
        except Exception as exc:
            return error_response(exc)

    @expose("/files/<file_id>/datasources", methods=("GET",))
    @protect()
    @safe
    def file_datasources(self, file_id: str) -> Response:
        """List datasets created from a file.

        ---
        get:
            description: List datasets created from a file.
            responses:
                200:
                    description: Dataset list
                401:
                    $ref: '#/components/responses/401'
        """
        try:
            result = get_services().datasources.list_for_file(permissions.current_user_id(), file_id)
            return self.response(200, result=result)
        except Exception as exc:
            return error_response(exc)

    @expose("/admin/cleanup", methods=("POST",))
    @protect()
    @safe
    def run_cleanup(self) -> Response:
        """Run expiry cleanup (force=True is admin-only).

        ---
        post:
            description: Run expiry cleanup (force=True is admin-only).
            responses:
                200:
                    description: Deleted file ids
                401:
                    $ref: '#/components/responses/401'
        """
        try:
            body = request.get_json(silent=True) or {}
            result = get_services().datasources.cleanup(
                permissions.current_user_id(), bool(body.get("force", False))
            )
            return self.response(200, result=result)
        except Exception as exc:
            return error_response(exc)
