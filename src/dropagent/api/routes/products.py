"""
Product routes: listing, retrieval, and approval/rejection actions.

All endpoints are wired to :class:`ProductRepository` through the
``get_product_repo`` dependency, which is overridable in tests.
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from dropagent.api.deps import ProductRepoDep
from dropagent.db.models import Product

router = APIRouter(prefix="/products", tags=["products"])

# Status values used by the approval actions.
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"


class ProductOut(BaseModel):
    """Serialized representation of a :class:`Product`."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ali_product_id: str
    naver_product_id: str | None = None
    product_name_en: str | None = None
    product_name_ko: str | None = None
    category_ali: str | None = None
    category_naver: str | None = None
    price_ali: Decimal | None = None
    price_naver: Decimal | None = None
    margin_rate: Decimal | None = None
    priority_score: Decimal | None = None
    risk_score: Decimal | None = None
    ops_cost_score: Decimal | None = None
    demand_score: Decimal | None = None
    status: str


@router.get("/", response_model=list[ProductOut])
async def list_products(
    repo: ProductRepoDep,
    status: str | None = Query(default=None, description="Filter by product status"),
    limit: int = Query(default=100, ge=1, le=500, description="Maximum number of products"),
) -> list[Product]:
    """List products, optionally filtered by status."""
    return await repo.list_all(status=status, limit=limit)


@router.get("/{product_id}", response_model=ProductOut)
async def get_product(product_id: int, repo: ProductRepoDep) -> Product:
    """Get a single product by ID, or 404 if it does not exist."""
    product = await repo.get_by_id(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.post("/{product_id}/approve", response_model=ProductOut)
async def approve_product(product_id: int, repo: ProductRepoDep) -> Product:
    """Approve a product, setting its status to ``approved``."""
    if await repo.get_by_id(product_id) is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return await repo.update_status(product_id, STATUS_APPROVED)


@router.post("/{product_id}/reject", response_model=ProductOut)
async def reject_product(product_id: int, repo: ProductRepoDep) -> Product:
    """Reject a product, setting its status to ``rejected``."""
    if await repo.get_by_id(product_id) is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return await repo.update_status(product_id, STATUS_REJECTED)
