"""RFC 9457 ``application/problem+json`` error handling (docs/02 §9).

The API never leaks internals to clients: handlers emit a structured problem
document (type/title/status/detail) while the full exception context goes to logs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from flask import jsonify
from werkzeug.exceptions import HTTPException

if TYPE_CHECKING:
    from flask import Flask, Response


class ProblemError(Exception):
    """An application error that maps directly to a problem+json response."""

    def __init__(
        self,
        status: int,
        title: str,
        detail: str | None = None,
        type_: str = "about:blank",
    ) -> None:
        super().__init__(title)
        self.status = status
        self.title = title
        self.detail = detail
        self.type = type_


def problem_response(
    status: int,
    title: str,
    detail: str | None = None,
    type_: str = "about:blank",
) -> Response:
    """Build a ``application/problem+json`` response."""
    body: dict[str, object] = {"type": type_, "title": title, "status": status}
    if detail is not None:
        body["detail"] = detail
    response = jsonify(body)
    response.status_code = status
    response.mimetype = "application/problem+json"
    return response


def register_error_handlers(app: Flask) -> None:
    """Register problem+json handlers for app errors, HTTP errors, and crashes."""

    @app.errorhandler(ProblemError)
    def _handle_problem(exc: ProblemError) -> Response:
        return problem_response(exc.status, exc.title, exc.detail, exc.type)

    @app.errorhandler(HTTPException)
    def _handle_http(exc: HTTPException) -> Response:
        return problem_response(exc.code or 500, exc.name, exc.description)

    @app.errorhandler(Exception)
    def _handle_uncaught(exc: Exception) -> Response:
        # Full context to logs; a generic, safe message to the client.
        app.logger.exception("unhandled_exception")
        return problem_response(500, "Internal Server Error", "An unexpected error occurred.")
