"""
Order routes: listing and retrieval.

Wired to :class:`OrderRepository` via the ``get_order_repo`` dependency, which
is overridable in tests.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from dropagent.api.deps import OrderRepoDep
from dropagent.db.models import Order

router = APIRouter(prefix="/orders", tags=["orders"])


class OrderOut(BaseModel):
    """Serialized representation of an :class:`Order`."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    naver_order_id: str
    ali_order_id: str | None = None
    product_id: int
    quantity: int
    total_price: Decimal
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


@router.get("/", response_model=list[OrderOut])
async def list_orders(
    repo: OrderRepoDep,
    status: str | None = Query(default=None, description="Filter by order status"),
    recent_hours: int | None = Query(
        default=None,
        ge=1,
        description="Return orders created within the last N hours",
    ),
    limit: int = Query(default=100, ge=1, le=500, description="Maximum number of orders"),
) -> list[Order]:
    """
    List orders.

    If ``status`` is given, filter by status. Otherwise, if ``recent_hours`` is
    given, return orders created within that window. With neither, default to
    the most recent 24 hours.
    """
    if status is not None:
        return await repo.list_by_status(status, limit=limit)
    hours = recent_hours if recent_hours is not None else 24
    return await repo.list_recent(hours=hours, limit=limit)


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(order_id: int, repo: OrderRepoDep) -> Order:
    """Get a single order by ID, or 404 if it does not exist."""
    order = await repo.get_by_id(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order
