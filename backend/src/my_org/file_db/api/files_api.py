"""Upload and file endpoints."""

from flask import Response, request
from flask_appbuilder.api import expose, protect, safe
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from .. import permissions
from . import error_response, get_services


@api(id="file_db_files_api", name="File DB Files API", description="Upload and manage files")
class FilesApi(RestApi):
    openapi_spec_tag = "File DB Files"
    class_permission_name = "file_db_files"

    @expose("/upload/init", methods=("POST",))
    @protect()
    @safe
    def init_upload(self) -> Response:
        """Start a chunked upload session.

        ---
        post:
            description: Start a chunked upload session.
            responses:
                200:
                    description: Upload session created
                401:
                    $ref: '#/components/responses/401'
        """
        try:
            result = get_services().upload.init(permissions.current_user_id(), request.get_json(force=True))
            return self.response(200, result=result)
        except Exception as exc:
            return error_response(exc)

    @expose("/upload/<upload_id>/chunks/<int:chunk_index>", methods=("PUT",))
    @protect()
    @safe
    def upload_chunk(self, upload_id: str, chunk_index: int) -> Response:
        """Upload one chunk of an upload session.

        ---
        put:
            description: Upload one chunk of an upload session.
            responses:
                200:
                    description: Chunk accepted
                401:
                    $ref: '#/components/responses/401'
        """
        try:
            result = get_services().upload.chunk(
                permissions.current_user_id(), upload_id, chunk_index, request.get_data()
            )
            return self.response(200, result=result)
        except Exception as exc:
            return error_response(exc)

    @expose("/upload/<upload_id>/complete", methods=("POST",))
    @protect()
    @safe
    def complete_upload(self, upload_id: str) -> Response:
        """Assemble chunks and register the uploaded file.

        ---
        post:
            description: Assemble chunks and register the uploaded file.
            responses:
                200:
                    description: File registered
                401:
                    $ref: '#/components/responses/401'
        """
        try:
            result = get_services().upload.complete(permissions.current_user_id(), upload_id)
            return self.response(200, result=result)
        except Exception as exc:
            return error_response(exc)

    @expose("/upload/<upload_id>/abort", methods=("POST",))
    @protect()
    @safe
    def abort_upload(self, upload_id: str) -> Response:
        """Abort an upload session and drop its chunks.

        ---
        post:
            description: Abort an upload session and drop its chunks.
            responses:
                200:
                    description: Session aborted
                401:
                    $ref: '#/components/responses/401'
        """
        try:
            result = get_services().upload.abort(permissions.current_user_id(), upload_id)
            return self.response(200, result=result)
        except Exception as exc:
            return error_response(exc)

    @expose("/upload/<upload_id>", methods=("GET",))
    @protect()
    @safe
    def upload_status(self, upload_id: str) -> Response:
        """Return upload session progress.

        ---
        get:
            description: Return upload session progress.
            responses:
                200:
                    description: Upload status
                401:
                    $ref: '#/components/responses/401'
        """
        try:
            result = get_services().upload.status(permissions.current_user_id(), upload_id)
            return self.response(200, result=result)
        except Exception as exc:
            return error_response(exc)

    @expose("/files", methods=("GET",))
    @protect()
    @safe
    def get_files(self) -> Response:
        """List the current user's files.

        ---
        get:
            description: List the current user's files.
            responses:
                200:
                    description: File list
                401:
                    $ref: '#/components/responses/401'
        """
        try:
            result = get_services().files.list(permissions.current_user_id())
            return self.response(200, result=result)
        except Exception as exc:
            return error_response(exc)

    @expose("/files/<file_id>", methods=("GET",))
    @protect()
    @safe
    def get_file(self, file_id: str) -> Response:
        """Return one file with its sheets.

        ---
        get:
            description: Return one file with its sheets.
            responses:
                200:
                    description: File detail
                401:
                    $ref: '#/components/responses/401'
        """
        try:
            result = get_services().files.get(permissions.current_user_id(), file_id)
            return self.response(200, result=result)
        except Exception as exc:
            return error_response(exc)

    @expose("/files/<file_id>/preview", methods=("GET",))
    @protect()
    @safe
    def preview_file(self, file_id: str) -> Response:
        """Preview the first 100 rows of a file.

        ---
        get:
            description: Preview the first 100 rows of a file.
            responses:
                200:
                    description: Preview payload
                401:
                    $ref: '#/components/responses/401'
        """
        try:
            sheet_index = request.args.get("sheet_index", type=int)
            result = get_services().files.preview(permissions.current_user_id(), file_id, sheet_index)
            return self.response(200, result=result)
        except Exception as exc:
            return error_response(exc)

    @expose("/files/<file_id>/config", methods=("PUT",))
    @protect()
    @safe
    def save_file_config(self, file_id: str) -> Response:
        """Save file config (name/description, sheets, delimiter, encoding).

        ---
        put:
            description: Save file config (name/description, sheets, delimiter, encoding).
            responses:
                200:
                    description: Saved config
                401:
                    $ref: '#/components/responses/401'
        """
        try:
            result = get_services().files.save_config(
                permissions.current_user_id(), file_id, request.get_json(force=True) or {}
            )
            return self.response(200, result=result)
        except Exception as exc:
            return error_response(exc)

    @expose("/files/<file_id>/usage", methods=("GET",))
    @protect()
    @safe
    def file_usage(self, file_id: str) -> Response:
        """Return dataset/chart/dashboard usage for a file.

        ---
        get:
            description: Return dataset/chart/dashboard usage for a file.
            responses:
                200:
                    description: Usage counters
                401:
                    $ref: '#/components/responses/401'
        """
        try:
            result = get_services().files.usage(permissions.current_user_id(), file_id)
            return self.response(200, result=result)
        except Exception as exc:
            return error_response(exc)

    @expose("/files/<file_id>", methods=("DELETE",))
    @protect()
    @safe
    def delete_file(self, file_id: str) -> Response:
        """Delete a file, its datasources and stored data.

        ---
        delete:
            description: Delete a file, its datasources and stored data.
            responses:
                200:
                    description: Deletion result
                401:
                    $ref: '#/components/responses/401'
        """
        try:
            result = get_services().files.delete(permissions.current_user_id(), file_id)
            return self.response(200, result=result)
        except Exception as exc:
            return error_response(exc)

    @expose("/notifications", methods=("GET",))
    @protect()
    @safe
    def get_notifications(self) -> Response:
        """Return expiry notifications for the current user.

        ---
        get:
            description: Return expiry notifications for the current user.
            responses:
                200:
                    description: Notification list
                401:
                    $ref: '#/components/responses/401'
        """
        try:
            result = get_services().files.notifications(permissions.current_user_id())
            return self.response(200, result=result)
        except Exception as exc:
            return error_response(exc)
