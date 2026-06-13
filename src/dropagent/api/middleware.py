"""
HTTP middleware for the DropAgent API.

Provides a single ASGI middleware that:

    - logs each request (method, path, status, duration);
    - converts unhandled exceptions into structured JSON error responses
      instead of leaking stack traces, mapping :class:`APIError` /
      :class:`DropAgentError` to an appropriate status code where convenient.
"""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from dropagent.utils.exceptions import APIError, DropAgentError
from dropagent.utils.logging import get_logger

logger = get_logger(__name__)

CallNext = Callable[[Request], Awaitable[Response]]


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log requests and translate unhandled exceptions into JSON responses."""

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except DropAgentError as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            status_code = exc.status_code if isinstance(exc, APIError) and exc.status_code else 500
            logger.warning(
                "request_failed",
                method=request.method,
                path=request.url.path,
                status_code=status_code,
                duration_ms=round(duration_ms, 2),
                error=exc.message,
                error_type=type(exc).__name__,
            )
            return JSONResponse(
                status_code=status_code,
                content={"error": type(exc).__name__, "detail": exc.message},
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error(
                "request_error",
                method=request.method,
                path=request.url.path,
                status_code=500,
                duration_ms=round(duration_ms, 2),
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return JSONResponse(
                status_code=500,
                content={"error": "InternalServerError", "detail": "Internal server error"},
            )

        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
        )
        return response
