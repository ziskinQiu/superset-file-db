"""REST API package: service access and shared error mapping."""

from flask import Response, jsonify, make_response

from ..services import get_services  # re-exported for endpoint modules and tests


def error_response(exc: Exception) -> Response:
    """Map service exceptions onto HTTP status codes (plan Task 16)."""
    if isinstance(exc, PermissionError):
        status = 403
    elif isinstance(exc, ValueError):
        status = 400
    elif isinstance(exc, (KeyError, FileNotFoundError)):
        status = 404
    else:
        status = 500
    resp = make_response(jsonify({"message": str(exc)}), status)
    resp.headers["Content-Type"] = "application/json; charset=utf-8"
    return resp
