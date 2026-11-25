"""Shared structured API error response model."""

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Safe error body used by all non-validation API failures."""

    error: str
    message: str
    field: str | None
