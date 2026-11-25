"""FastAPI application factory and Phase 0 health endpoint."""

import logging
import re
from collections.abc import Callable
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import RequestResponseEndpoint

from apps.api.workflow import workflow_router
from eg_common import __version__
from eg_common.errors import AppError
from eg_common.logging import log_event
from eg_common.settings import Settings, get_settings
from persistence.session import database_is_available

_logger = logging.getLogger(__name__)
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _health_response(database_check: Callable[[], bool]) -> JSONResponse:
    """Build the contract health response from the database check result."""
    if database_check():
        return JSONResponse(
            status_code=200,
            content={"status": "ok", "version": __version__, "db": "ok"},
        )
    return JSONResponse(
        status_code=503,
        content={"status": "error", "version": __version__, "db": "error"},
    )


def create_app(
    settings: Settings | None = None,
    database_check: Callable[[], bool] | None = None,
) -> FastAPI:
    """Create the API application with configurable settings and health checking."""
    resolved_settings = settings or get_settings()
    resolved_database_check = database_check or database_is_available
    app = FastAPI(
        title="EvidenceGraph API",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def add_request_id(request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Attach a safe request identifier to request state and response headers."""
        supplied_request_id = request.headers.get("X-Request-ID", "")
        request_id = (
            supplied_request_id
            if _REQUEST_ID_PATTERN.fullmatch(supplied_request_id)
            else str(uuid4())
        )
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        """Convert expected application errors to the shared public shape."""
        return JSONResponse(
            status_code=exc.http_status,
            content={"error": exc.code, "message": exc.message, "field": exc.field},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Return safe structured responses for routing and HTTP errors."""
        if exc.status_code == 404:
            code, message = "not_found", "The requested resource was not found."
        elif exc.status_code == 405:
            code, message = "method_not_allowed", "The requested method is not allowed."
        else:
            code, message = "request_error", "The request could not be completed."
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": code, "message": message, "field": None},
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, _exc: Exception) -> JSONResponse:
        """Return a generic error without exposing exception or document content."""
        log_event(_logger, "request_failed", error_code="internal_error", level=logging.ERROR)
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": "An internal error occurred.",
                "field": None,
            },
            headers={"X-Request-ID": request.state.request_id},
        )

    def api_health() -> JSONResponse:
        """Report API and database readiness using the frontend health contract."""
        return _health_response(resolved_database_check)

    def health_alias() -> JSONResponse:
        """Serve the Docker health check at the root alias."""
        return _health_response(resolved_database_check)

    app.add_api_route(
        "/api/v1/health",
        api_health,
        methods=["GET"],
        name="health",
    )
    app.add_api_route(
        "/health",
        health_alias,
        methods=["GET"],
        include_in_schema=False,
        name="health_alias",
    )
    app.include_router(workflow_router(resolved_settings))
    return app


app = create_app()
