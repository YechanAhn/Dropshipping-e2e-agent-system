"""
Product routes: listing, retrieval, and approval/rejection actions.

All endpoints are wired to :class:`ProductRepository` through the
``get_product_repo`` dependency, which is overridable in tests.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, field_validator

from dropagent.api.deps import ProductRepoDep
from dropagent.clients.aliexpress import get_ali_client
from dropagent.core.detail_page import render_detail_page
from dropagent.db.models import Product
from dropagent.utils.logging import get_logger

router = APIRouter(prefix="/products", tags=["products"])
logger = get_logger(__name__)

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
    # Money/score fields are emitted as JSON numbers (not Decimal strings) so the
    # dashboard's number formatting/arithmetic works directly. KRW are whole won,
    # exact in float64.
    price_ali: float | None = None  # AliExpress sale price, in KRW (target_currency=KRW)
    price_ali_krw: float | None = None  # alias of price_ali (already KRW); kept for dashboard
    price_naver: float | None = None
    # 최저가 노출 추적
    naver_catalog_lowest: float | None = None  # 가격비교 대표(catalog) 최저가 = 배지가
    naver_price_min_market: float | None = None  # 검색결과 전체 최저가 (단독 포함)
    is_price_lowest: bool = False  # 현재 최저가(배지) 보유 여부
    price_floor: float | None = None  # 마진 하한 가격
    pricing_strategy: str | None = None  # catalog_match | standalone
    last_repriced_at: datetime | None = None
    # 파생값 (대시보드용)
    price_gap: float | None = None  # price_naver - naver_catalog_lowest (양수면 더 비쌈)
    badge_at_risk: bool = False  # 최저가보다 비싸 배지 미확보 → 노출 위험
    margin_rate: float | None = None
    priority_score: float | None = None
    risk_score: float | None = None
    ops_cost_score: float | None = None
    demand_score: float | None = None
    status: str

    @field_validator("is_price_lowest", "badge_at_risk", mode="before")
    @classmethod
    def _none_to_false(cls, v: object) -> bool:
        """Transient (un-flushed) Product rows have None here; treat as False."""
        return bool(v)


def _serialize(product: Product) -> ProductOut:
    """
    Serialize a product. ``price_ali`` is sourced from AliExpress already in KRW
    (target_currency=KRW), so no FX conversion happens here -- ``price_ali_krw``
    simply mirrors it for the dashboard. ``price_gap``/``badge_at_risk`` are
    derived from our Naver price vs the catalog 최저가.
    """
    out = ProductOut.model_validate(product)
    out.price_ali_krw = out.price_ali
    if out.price_naver is not None and out.naver_catalog_lowest is not None:
        out.price_gap = out.price_naver - out.naver_catalog_lowest
        out.badge_at_risk = out.price_naver > out.naver_catalog_lowest
    return out


@router.get("/", response_model=list[ProductOut])
async def list_products(
    repo: ProductRepoDep,
    status: str | None = Query(default=None, description="Filter by product status"),
    limit: int = Query(default=100, ge=1, le=500, description="Maximum number of products"),
) -> list[ProductOut]:
    """List products, optionally filtered by status."""
    products = await repo.list_all(status=status, limit=limit)
    return [_serialize(p) for p in products]


@router.get("/{product_id}", response_model=ProductOut)
async def get_product(product_id: int, repo: ProductRepoDep) -> ProductOut:
    """Get a single product by ID, or 404 if it does not exist."""
    product = await repo.get_by_id(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return _serialize(product)


@router.get("/{product_id}/detail-preview", response_class=HTMLResponse)
async def detail_preview(product_id: int, repo: ProductRepoDep) -> HTMLResponse:
    """Render the auto-generated Korean 상세페이지 for a product (preview).

    Pulls live AliExpress DS detail (images/video/description/options) for the
    product's real itemId and renders the deterministic 11-section Korean page.
    Falls back to the product's stored fields when no DS detail is available
    (e.g. unmatched product or DS error), so the preview never errors.
    """
    product = await repo.get_by_id(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    detail = None
    ali_id = product.ali_product_id or ""
    if ali_id and not ali_id.startswith("PENDING-"):
        client = get_ali_client()
        try:
            ds = await client.get_product_detail([ali_id])
            detail = ds[0] if ds else None
        except Exception as exc:  # noqa: BLE001 - preview must never 500
            logger.warning("detail_preview_ds_failed", product_id=product_id, error=str(exc))
        finally:
            await client.close()

    html = render_detail_page(
        detail or product,
        naver_title=product.product_name_ko,
        recommended_price=product.price_naver,
    )
    return HTMLResponse(content=html)


@router.post("/{product_id}/approve", response_model=ProductOut)
async def approve_product(product_id: int, repo: ProductRepoDep) -> ProductOut:
    """Approve a product, setting its status to ``approved``."""
    if await repo.get_by_id(product_id) is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return _serialize(await repo.update_status(product_id, STATUS_APPROVED))


@router.post("/{product_id}/reject", response_model=ProductOut)
async def reject_product(product_id: int, repo: ProductRepoDep) -> ProductOut:
    """Reject a product, setting its status to ``rejected``."""
    if await repo.get_by_id(product_id) is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return _serialize(await repo.update_status(product_id, STATUS_REJECTED))
