"""
Utility package for DropAgent.

Provides shared helpers used across the project:
    - **currency**: CNY/USD to KRW conversion with exchange-rate buffers.
    - **exceptions**: Domain-specific exception hierarchy.
    - **logging**: Structured logging setup via *structlog*.
    - **validators**: Input validation and HTML sanitisation.
"""

# Currency helpers
from dropagent.utils.currency import (
    apply_exchange_buffer,
    convert_cny_to_krw,
    convert_usd_to_krw,
    convert_with_buffer,
)

# Custom exceptions
from dropagent.utils.exceptions import (
    APIError,
    ConfigurationError,
    DatabaseError,
    DataCollectionError,
    DropAgentError,
    IdempotencyError,
    RateLimitError,
    RegistrationError,
    ScoreCalculationError,
    ValidationError,
)

# Logging
from dropagent.utils.logging import get_logger, setup_logging

# Validators / sanitisation
from dropagent.utils.validators import (
    sanitize_html,
    validate_ali_product_id,
    validate_category,
    validate_naver_product_id,
    validate_price,
    validate_url,
)

__all__ = [
    # Currency
    "convert_cny_to_krw",
    "convert_usd_to_krw",
    "apply_exchange_buffer",
    "convert_with_buffer",
    # Exceptions
    "DropAgentError",
    "APIError",
    "RateLimitError",
    "DataCollectionError",
    "RegistrationError",
    "ScoreCalculationError",
    "IdempotencyError",
    "DatabaseError",
    "ValidationError",
    "ConfigurationError",
    # Logging
    "setup_logging",
    "get_logger",
    # Validators
    "validate_ali_product_id",
    "validate_naver_product_id",
    "validate_price",
    "validate_category",
    "validate_url",
    "sanitize_html",
]
