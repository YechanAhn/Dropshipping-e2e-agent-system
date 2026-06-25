"""
FastAPI application factory for the DropAgent HTTP API.

Use :func:`create_app` to build a configured application instance::

    from dropagent.api.app import create_app

    app = create_app()

Then run it with uvicorn, e.g. ``uvicorn dropagent.api.app:create_app --factory``.
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dropagent.api.middleware import RequestLoggingMiddleware
from dropagent.api.routes import analytics, orders, products, settings

# Origins allowed to call the API from a browser (the Next.js dashboard). Local
# dev defaults (3000 and 3001, since Next falls back to 3001 when 3000 is taken);
# extend via the comma-separated DASHBOARD_ORIGINS env var.
DEFAULT_DASHBOARD_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
]


def _dashboard_origins() -> list[str]:
    extra = os.environ.get("DASHBOARD_ORIGINS", "")
    origins = list(DEFAULT_DASHBOARD_ORIGINS)
    origins.extend(o.strip() for o in extra.split(",") if o.strip())
    return origins


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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_dashboard_origins(),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(products.router)
    app.include_router(orders.router)
    app.include_router(analytics.router)
    app.include_router(settings.router)

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok"}

    return app
