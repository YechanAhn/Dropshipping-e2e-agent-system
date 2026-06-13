"""
FastAPI application factory for the DropAgent HTTP API.

Use :func:`create_app` to build a configured application instance::

    from dropagent.api.app import create_app

    app = create_app()

Then run it with uvicorn, e.g. ``uvicorn dropagent.api.app:create_app --factory``.
"""
from __future__ import annotations

from fastapi import FastAPI

from dropagent.api.middleware import RequestLoggingMiddleware
from dropagent.api.routes import analytics, orders, products, settings


def create_app() -> FastAPI:
    """
    Build and configure the FastAPI application.

    Adds request-logging / error-handling middleware, registers the product,
    order, analytics, and settings routers, and exposes a ``/health`` endpoint.

    Returns:
        A configured :class:`FastAPI` instance.
    """
    app = FastAPI(
        title="DropAgent API",
        description="HTTP API for the Naver x AliExpress dropshipping system.",
        version="0.1.0",
    )

    app.add_middleware(RequestLoggingMiddleware)

    app.include_router(products.router)
    app.include_router(orders.router)
    app.include_router(analytics.router)
    app.include_router(settings.router)

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok"}

    return app
