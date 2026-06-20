#!/usr/bin/env python
"""
Seed the DB with REAL end-to-end opportunities (Naver demand + AliExpress source).

For each keyword:
  1. Naver Shopping Search (sort=sim) -> catalog 최저가, market floor, median,
     catalog ratio (real Korean market data; the valid NAVER_CLIENT credentials).
  2. AliExpress DS API (aliexpress.ds.text.search) -> the top matching product
     with its KRW price, title, real itemId (the DS access_token in .env).
  3. Pricing: landed cost from the Ali KRW price -> lowest_for_exposure (catalog
     match, margin-floor-guarded) so price_naver / margin_rate / price_floor fill.

Result: Products carrying REAL Ali source price (KRW), a margin-feasible Naver
sale price, and the 최저가 exposure context -- the dashboard's ALI/판매가/마진율
columns fill with live data. Nothing is fabricated; if a side has no data the
corresponding fields stay null.

Rows are upserted by the real Ali itemId.

Usage:
    python scripts/seed_real_naver.py "무선이어폰" "캠핑 의자" --display 40
"""

import argparse
import asyncio
import statistics
import sys
from decimal import Decimal

from dropagent.clients.aliexpress import get_ali_client
from dropagent.clients.naver.models import CATALOG_PARENT_PRODUCT_TYPES, STANDALONE_PRODUCT_TYPES
from dropagent.clients.naver.shopping_api import NaverShoppingClient
from dropagent.config import get_settings
from dropagent.core.pricing import lowest_for_exposure, optimal_price
from dropagent.db.repositories.product_repo import ProductRepository
from dropagent.db.session import get_db_session
from dropagent.pipeline.sourcing import estimate_landed_cost


def _dec(value) -> Decimal | None:  # noqa: ANN001
    return Decimal(str(value)) if value else None


def _score(value: float, cap: float = 100.0) -> Decimal:
    return Decimal(str(round(min(cap, max(0.0, value)), 2)))


async def _naver_market(shopping: NaverShoppingClient, keyword: str, display: int) -> dict:
    """Aggregate real Naver market data for *keyword* (sort=sim)."""
    result = await shopping.search(query=keyword, display=display, sort="sim")
    items = [it for it in result.items if it.lowest_price > 0]
    if not items:
        return {}
    prices = [it.lowest_price for it in items]
    catalog = [it.lowest_price for it in items if it.product_type in CATALOG_PARENT_PRODUCT_TYPES]
    standalone = sum(1 for it in items if it.product_type in STANDALONE_PRODUCT_TYPES)
    return {
        "price_min": min(prices),
        "price_median": int(statistics.median(prices)),
        "catalog_lowest": min(catalog) if catalog else 0,
        "catalog_ratio": round(1.0 - standalone / len(items), 4),
        "category": next((it.category2 or it.category1 for it in items if it.category1), ""),
        "total": result.total,
    }


async def _seed_keyword(repo, shopping, ali, keyword: str, display: int) -> str:  # noqa: ANN001
    market = await _naver_market(shopping, keyword, display)
    if not market:
        return "no-naver"

    # AliExpress source: top product for the keyword (DS, KRW prices).
    search = await ali.search_products(keyword, page_size=10)
    top = search.products[0] if search.products else None
    if top is None:
        return "no-ali"

    landed = estimate_landed_cost(top)  # KRW (target_currency=KRW) -> no FX
    catalog_lowest = market["catalog_lowest"]
    if catalog_lowest > 0:
        pricing = lowest_for_exposure(landed, catalog_lowest, market_floor=market["price_min"] or None)
        strategy = "catalog_match"
    else:
        pricing = optimal_price(landed, [market["price_median"]] if market["price_median"] else [])
        strategy = "standalone"

    fields = {
        "product_name_ko": keyword,
        "product_name_en": top.title,
        "category_ali": top.category_id,
        "category_naver": market["category"] or None,
        "price_ali": _dec(top.price.sale_price),  # real Ali source price, KRW
        "price_naver": pricing.recommended_price if pricing.recommended_price > 0 else None,
        "naver_catalog_lowest": _dec(catalog_lowest),
        "naver_price_min_market": _dec(market["price_min"]),
        "price_floor": _dec(pricing.floor_price),
        "pricing_strategy": strategy,
        "margin_rate": _dec(round(pricing.expected_margin_rate, 4)),
        "priority_score": _score((1.0 - market["catalog_ratio"]) * 100.0),
        "demand_score": _score(min(len(str(market["total"])) * 14.0, 100.0)),
        "ops_cost_score": _score(market["catalog_ratio"] * 100.0),
        "status": "candidate",
    }

    existing = await repo.get_by_ali_id(top.product_id)
    if existing is not None:
        await repo.update(existing.id, fields)
        return "updated"
    await repo.create({"ali_product_id": top.product_id, **fields})
    return "created"


async def _run(args: argparse.Namespace) -> int:
    try:
        settings = get_settings()
    except Exception as exc:  # noqa: BLE001
        print(f"[config error] {exc}", file=sys.stderr)
        return 2

    shopping = NaverShoppingClient(settings.naver)
    ali = get_ali_client(settings.aliexpress)
    print(f"AliExpress client: {type(ali).__name__}")
    counts: dict[str, int] = {}
    try:
        async with get_db_session() as session:
            repo = ProductRepository(session)
            for keyword in args.keywords:
                try:
                    outcome = await _seed_keyword(repo, shopping, ali, keyword, args.display)
                except Exception as exc:  # noqa: BLE001
                    outcome = f"error: {exc}"
                counts[outcome] = counts.get(outcome, 0) + 1
                print(f"  {keyword}: {outcome}")
    finally:
        await shopping.close()
        await ali.close()

    print(f"\nDone: {counts}")
    return 0


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed DB with real Naver+AliExpress opportunities")
    p.add_argument(
        "keywords",
        nargs="*",
        default=["무선이어폰", "캠핑 의자", "강아지 장난감", "주방 정리함", "휴대용 선풍기"],
        help="Product keywords to source",
    )
    p.add_argument("--display", type=int, default=40, help="Naver results per keyword to aggregate")
    return p.parse_args()


def main() -> None:
    raise SystemExit(asyncio.run(_run(_parse_args())))


if __name__ == "__main__":
    main()
