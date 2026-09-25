"""Column configuration endpoints."""

from flask import Response, request
from flask_appbuilder.api import expose, protect, safe
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from .. import permissions
from . import error_response, get_services


@api(id="file_db_columns_api", name="File DB Columns API", description="Manage column types")
class ColumnsApi(RestApi):
    openapi_spec_tag = "File DB Columns"
    class_permission_name = "file_db_columns"

    @expose("/files/<file_id>/columns", methods=("GET",))
    @protect()
    @safe
    def get_columns(self, file_id: str) -> Response:
        """List columns with inferred/user-defined types.

        ---
        get:
            description: List columns with inferred/user-defined types.
            responses:
                200:
                    description: Column list
                401:
                    $ref: '#/components/responses/401'
        """
        try:
            sheet_id = request.args.get("sheet_id")
            result = get_services().columns.list(permissions.current_user_id(), file_id, sheet_id)
            return self.response(200, result=result)
        except Exception as exc:
            return error_response(exc)

    @expose("/files/<file_id>/columns/<column_id>", methods=("PUT",))
    @protect()
    @safe
    def update_column(self, file_id: str, column_id: str) -> Response:
        """Update one column type (writes permanent history).

        ---
        put:
            description: Update one column type (writes permanent history).
            responses:
                200:
                    description: Updated column
                401:
                    $ref: '#/components/responses/401'
        """
        try:
            body = request.get_json(force=True) or {}
            result = get_services().columns.update(
                permissions.current_user_id(),
                file_id,
                column_id,
                body.get("type"),
                body.get("format"),
            )
            return self.response(200, result=result)
        except Exception as exc:
            return error_response(exc)

    @expose("/files/<file_id>/columns/import", methods=("POST",))
    @protect()
    @safe
    def import_columns(self, file_id: str) -> Response:
        """Import a column config JSON (all-or-nothing).

        ---
        post:
            description: Import a column config JSON (all-or-nothing).
            responses:
                200:
                    description: Applied count
                401:
                    $ref: '#/components/responses/401'
        """
        try:
            result = get_services().columns.import_config(
                permissions.current_user_id(), file_id, request.get_json(force=True)
            )
            return self.response(200, result=result)
        except Exception as exc:
            return error_response(exc)

    @expose("/files/<file_id>/columns/history", methods=("GET",))
    @protect()
    @safe
    def column_history(self, file_id: str) -> Response:
        """List the permanent column change history.

        ---
        get:
            description: List the permanent column change history.
            responses:
                200:
                    description: Change history
                401:
                    $ref: '#/components/responses/401'
        """
        try:
            result = get_services().columns.history(permissions.current_user_id(), file_id)
            return self.response(200, result=result)
        except Exception as exc:
            return error_response(exc)
