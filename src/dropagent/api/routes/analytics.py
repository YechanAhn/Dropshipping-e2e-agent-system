"""
Analytics routes: dashboard summary aggregating revenue, order counts, and
trending keywords.

Combines :class:`OrderRepository` and :class:`AnalyticsRepository`, both
injected via overridable dependencies.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from dropagent.api.deps import AnalyticsRepoDep, OrderRepoDep

router = APIRouter(prefix="/analytics", tags=["analytics"])


class AnalyticsSummary(BaseModel):
    """Dashboard summary payload."""

    revenue_summary: dict[str, Any]
    order_counts: dict[str, int]
    top_trending_keywords: list[dict[str, Any]]


@router.get("/summary", response_model=AnalyticsSummary)
async def get_summary(
    order_repo: OrderRepoDep,
    analytics_repo: AnalyticsRepoDep,
    days: int = Query(default=30, ge=1, le=365, description="Revenue window in days"),
    keyword_limit: int = Query(default=20, ge=1, le=100, description="Number of keywords"),
) -> AnalyticsSummary:
    """Return revenue summary, order counts by status, and trending keywords."""
    revenue_summary = await order_repo.get_revenue_summary(days=days)
    order_counts = await order_repo.count_by_status()
    top_trending_keywords = await analytics_repo.get_top_trending_keywords(limit=keyword_limit)
    return AnalyticsSummary(
        revenue_summary=revenue_summary,
        order_counts=order_counts,
        top_trending_keywords=top_trending_keywords,
    )
