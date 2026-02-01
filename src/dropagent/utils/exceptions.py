"""
Custom exception classes for DropAgent system.
"""
from typing import Any


class DropAgentError(Exception):
    """Base exception for all DropAgent errors."""

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
        original_error: Exception | None = None,
    ):
        self.message = message
        self.details = details or {}
        self.original_error = original_error
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} | Details: {self.details}"
        return self.message

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(message={self.message!r}, details={self.details!r})"


class APIError(DropAgentError):
    """Exception for external API errors."""

    def __init__(
        self,
        message: str,
        api_name: str | None = None,
        status_code: int | None = None,
        response_body: str | None = None,
        details: dict[str, Any] | None = None,
        original_error: Exception | None = None,
    ):
        self.api_name = api_name
        self.status_code = status_code
        self.response_body = response_body

        error_details = details or {}
        if api_name:
            error_details["api_name"] = api_name
        if status_code:
            error_details["status_code"] = status_code
        if response_body:
            error_details["response_body"] = response_body

        super().__init__(message=message, details=error_details, original_error=original_error)


class RateLimitError(APIError):
    """Exception for API rate limit errors (HTTP 429)."""

    def __init__(
        self,
        message: str = "API rate limit exceeded",
        api_name: str | None = None,
        retry_after: int | None = None,
        details: dict[str, Any] | None = None,
        original_error: Exception | None = None,
    ):
        self.retry_after = retry_after

        error_details = details or {}
        if retry_after:
            error_details["retry_after"] = retry_after

        super().__init__(
            message=message,
            api_name=api_name,
            status_code=429,
            details=error_details,
            original_error=original_error,
        )


class DataCollectionError(DropAgentError):
    """Exception for data collection process errors."""

    def __init__(
        self,
        message: str,
        source: str | None = None,
        product_id: str | None = None,
        details: dict[str, Any] | None = None,
        original_error: Exception | None = None,
    ):
        self.source = source
        self.product_id = product_id

        error_details = details or {}
        if source:
            error_details["source"] = source
        if product_id:
            error_details["product_id"] = product_id

        super().__init__(message=message, details=error_details, original_error=original_error)


class RegistrationError(DropAgentError):
    """Exception for product registration errors."""

    def __init__(
        self,
        message: str,
        platform: str | None = None,
        product_id: str | None = None,
        details: dict[str, Any] | None = None,
        original_error: Exception | None = None,
    ):
        self.platform = platform
        self.product_id = product_id

        error_details = details or {}
        if platform:
            error_details["platform"] = platform
        if product_id:
            error_details["product_id"] = product_id

        super().__init__(message=message, details=error_details, original_error=original_error)


class ScoreCalculationError(DropAgentError):
    """Exception for product scoring calculation errors."""

    def __init__(
        self,
        message: str,
        product_id: str | None = None,
        metric: str | None = None,
        details: dict[str, Any] | None = None,
        original_error: Exception | None = None,
    ):
        self.product_id = product_id
        self.metric = metric

        error_details = details or {}
        if product_id:
            error_details["product_id"] = product_id
        if metric:
            error_details["metric"] = metric

        super().__init__(message=message, details=error_details, original_error=original_error)


class IdempotencyError(DropAgentError):
    """Exception for duplicate operation attempts."""

    def __init__(
        self,
        message: str = "Operation already executed",
        operation_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
        original_error: Exception | None = None,
    ):
        self.operation_id = operation_id
        self.resource_type = resource_type
        self.resource_id = resource_id

        error_details = details or {}
        if operation_id:
            error_details["operation_id"] = operation_id
        if resource_type:
            error_details["resource_type"] = resource_type
        if resource_id:
            error_details["resource_id"] = resource_id

        super().__init__(message=message, details=error_details, original_error=original_error)


class DatabaseError(DropAgentError):
    """Exception for database operation errors."""

    def __init__(
        self,
        message: str,
        operation: str | None = None,
        table: str | None = None,
        details: dict[str, Any] | None = None,
        original_error: Exception | None = None,
    ):
        self.operation = operation
        self.table = table

        error_details = details or {}
        if operation:
            error_details["operation"] = operation
        if table:
            error_details["table"] = table

        super().__init__(message=message, details=error_details, original_error=original_error)


class ValidationError(DropAgentError):
    """Exception for data validation errors."""

    def __init__(
        self,
        message: str,
        field: str | None = None,
        value: Any | None = None,
        details: dict[str, Any] | None = None,
        original_error: Exception | None = None,
    ):
        self.field = field
        self.value = value

        error_details = details or {}
        if field:
            error_details["field"] = field
        if value is not None:
            error_details["value"] = str(value)

        super().__init__(message=message, details=error_details, original_error=original_error)


class ConfigurationError(DropAgentError):
    """Exception for configuration errors."""

    def __init__(
        self,
        message: str,
        config_key: str | None = None,
        details: dict[str, Any] | None = None,
        original_error: Exception | None = None,
    ):
        self.config_key = config_key

        error_details = details or {}
        if config_key:
            error_details["config_key"] = config_key

        super().__init__(message=message, details=error_details, original_error=original_error)
