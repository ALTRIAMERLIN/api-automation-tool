"""Expected error types and their CLI exit codes (SPEC section 16)."""

from __future__ import annotations


class AppError(Exception):
    """Base class for every expected error. Carries a message safe to show."""

    exit_code: int = 1

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return self.message


class ConfigError(AppError):
    """A job or setting is invalid. ``errors`` holds ``(field, message)`` pairs."""

    exit_code = 2

    def __init__(self, errors: list[tuple[str, str]]) -> None:
        self.errors = list(errors)
        message = "; ".join(f"{field}: {msg}" for field, msg in self.errors)
        super().__init__(message)


class JobNotFoundError(AppError):
    exit_code = 2


class JobBusyError(AppError):
    exit_code = 2


class HttpError(AppError):
    exit_code = 1

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class NetworkError(AppError):
    exit_code = 1


class InvalidResponseError(AppError):
    exit_code = 1


class PaginationError(AppError):
    exit_code = 1


class TransformError(AppError):
    exit_code = 1


class ExportError(AppError):
    exit_code = 1
