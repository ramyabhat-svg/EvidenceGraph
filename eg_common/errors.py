"""Safe, structured application errors for API responses."""


class AppError(Exception):
    """An expected application failure with a safe public error shape."""

    def __init__(
        self,
        code: str,
        message: str,
        field: str | None = None,
        http_status: int = 400,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field
        self.http_status = http_status


class NotFoundError(AppError):
    """An application resource could not be found."""

    def __init__(self, message: str = "The requested resource was not found.") -> None:
        super().__init__("not_found", message, http_status=404)


class ConflictError(AppError):
    """A request conflicts with the current application state."""

    def __init__(self, code: str, message: str, field: str | None = None) -> None:
        super().__init__(code, message, field, http_status=409)
