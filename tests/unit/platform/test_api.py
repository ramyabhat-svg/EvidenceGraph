"""Phase 0 API contract tests."""

from fastapi.testclient import TestClient

from apps.api.main import create_app
from eg_common import __version__
from eg_common.errors import AppError
from eg_common.settings import Settings


def _client(database_available: bool = True) -> TestClient:
    """Create a test client with an isolated health check result."""
    settings = Settings(_env_file=None)
    return TestClient(
        create_app(settings, database_check=lambda: database_available),
        raise_server_exceptions=False,
    )


def test_health_routes_return_exact_success_and_failure_bodies() -> None:
    """Both health paths report the same exact contract for available or down DBs."""
    for path in ("/api/v1/health", "/health"):
        success = _client().get(path)
        assert success.status_code == 200
        assert success.json() == {"status": "ok", "version": __version__, "db": "ok"}

        failure = _client(database_available=False).get(path)
        assert failure.status_code == 503
        assert failure.json() == {
            "status": "error",
            "version": __version__,
            "db": "error",
        }


def test_app_errors_use_the_shared_error_shape() -> None:
    """Expected application errors retain code, safe message, and field."""
    app = create_app(Settings(_env_file=None), database_check=lambda: True)

    @app.get("/api/v1/failure")
    def failure() -> None:
        raise AppError("invalid_file_type", "Unsupported upload type.", "file", 400)

    response = TestClient(app).get("/api/v1/failure")

    assert response.status_code == 400
    assert response.json() == {
        "error": "invalid_file_type",
        "message": "Unsupported upload type.",
        "field": "file",
    }


def test_unknown_path_has_structured_not_found_body() -> None:
    """Unknown paths use the required 404 error object."""
    response = _client().get("/api/v1/missing")

    assert response.status_code == 404
    assert response.json() == {
        "error": "not_found",
        "message": "The requested resource was not found.",
        "field": None,
    }


def test_unhandled_error_does_not_leak_exception_text() -> None:
    """Unexpected exception details are hidden from clients."""
    app = create_app(Settings(_env_file=None), database_check=lambda: True)

    @app.get("/api/v1/crash")
    def crash() -> None:
        raise RuntimeError("private document content")

    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/crash")

    assert response.status_code == 500
    assert response.json() == {
        "error": "internal_error",
        "message": "An internal error occurred.",
        "field": None,
    }
    assert "private document content" not in response.text
    assert response.headers["X-Request-ID"]


def test_validation_error_keeps_fastapi_default_shape() -> None:
    """FastAPI request validation errors remain unmodified 422 responses."""
    app = create_app(Settings(_env_file=None), database_check=lambda: True)

    @app.get("/api/v1/typed")
    def typed(value: int) -> dict[str, int]:
        return {"value": value}

    response = TestClient(app).get("/api/v1/typed", params={"value": "not-an-int"})

    assert response.status_code == 422
    assert set(response.json()) == {"detail"}


def test_request_id_is_preserved_or_generated() -> None:
    """Requests receive a safe X-Request-ID response header."""
    client = _client()

    supplied = client.get("/api/v1/health", headers={"X-Request-ID": "req-123"})
    generated = client.get("/api/v1/health", headers={"X-Request-ID": "bad\r\nvalue"})

    assert supplied.headers["X-Request-ID"] == "req-123"
    assert generated.headers["X-Request-ID"]
    assert "\r" not in generated.headers["X-Request-ID"]


def test_cors_allows_configured_origin_and_post_preflight() -> None:
    """Configured web origin is allowed for GET and POST requests."""
    response = _client().options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "POST" in response.headers["access-control-allow-methods"]


def test_cors_does_not_allow_an_unconfigured_origin() -> None:
    """An unrelated origin receives no allow-origin header."""
    response = _client().get("/api/v1/health", headers={"Origin": "https://other.example"})

    assert "access-control-allow-origin" not in response.headers


def test_api_routes_use_versioned_prefix_except_health_alias() -> None:
    """All application routes are versioned apart from the Docker health alias."""
    app = create_app(Settings(_env_file=None), database_check=lambda: True)
    paths = {route.path for route in app.routes}

    assert paths == {"/api/v1/health", "/health"}
    assert all(path.startswith("/api/v1/") or path == "/health" for path in paths)
