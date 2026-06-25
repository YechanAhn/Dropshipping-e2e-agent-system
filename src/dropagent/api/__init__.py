"""
FastAPI application package for DropAgent.

Provides the REST API layer including route modules, middleware, and
dependency injection helpers:

    - **routes.products**: Product CRUD and listing endpoints.
    - **routes.orders**: Order management endpoints.
    - **routes.analytics**: Dashboard analytics endpoints.
    - **routes.settings**: System configuration endpoints.
    - **middleware**: Request logging, error handling, CORS.
    - **deps**: Shared FastAPI dependencies (DB session, auth, etc.).
"""
from dropagent.api.app import create_app

__all__ = ["create_app"]
