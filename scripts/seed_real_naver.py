#!/usr/bin/env python
"""
Seed the DB with REAL Naver market data via the Naver Shopping Search API.

For each keyword this fetches the live relevance-ranked results (sort=sim, the
representative view -- NOT sort=asc, which surfaces 1원 미끼상품 for broad terms)
and persists a ``Product`` carrying REAL Naver data: the catalog 최저가 (badge
price), the overall market floor, the median market price, the catalog ratio,
and a representative image.

Only the Naver Shopping Search API is used (NAVER_CLIENT_ID/SECRET), which is
the credential set that is actually valid. The demand-first discovery pipeline
needs the Naver Search Ad API (absolute search volume) whose key is a
placeholder in .env, so it is intentionally NOT used here.

AliExpress-side fields (price_ali, the ALI match) stay NULL until valid ALI API
credentials are configured -- this script never fabricates ALI data. Rows are
keyed by a stable PENDING-<hash> ali_product_id so re-runs update in place.

Usage:
    python scripts/seed_real_naver.py "무선이어폰" "캠핑 의자" "강아지 장난감" --display 40
"""

import argparse
import asyncio
import hashlib
import sys
from decimal import Decimal

from dropagent.clients.naver.models import CATALOG_PARENT_PRODUCT_TYPES, STANDALONE_PRODUCT_TYPES
from dropagent.clients.naver.shopping_api import NaverShoppingClient
from dropagent.config import get_settings
from dropagent.db.repositories.product_repo import ProductRepository
from dropagent.db.session import get_db_session


def _dec(value: int | float | None) -> Decimal | None:
    return Decimal(str(value)) if value else None


def _score(value: float, cap: float = 100.0) -> Decimal:
    return Decimal(str(round(min(cap, max(0.0, value)), 2)))


def _pending_ali_id(keyword: str) -> str:
    return "PENDING-" + hashlib.sha1(keyword.encode("utf-8")).hexdigest()[:16]


async def _seed_keyword(
    repo: ProductRepository, shopping: NaverShoppingClient, keyword: str, display: int
) -> str:
    result = await shopping.search(query=keyword, display=display, sort="sim")
    items = [it for it in result.items if it.lowest_price > 0]
    if not items:
        return "empty"

    prices = [it.lowest_price for it in items]
    price_min = min(prices)
    catalog_prices = [it.lowest_price for it in items if it.product_type in CATALOG_PARENT_PRODUCT_TYPES]
    catalog_lowest = min(catalog_prices) if catalog_prices else 0
    standalone = sum(1 for it in items if it.product_type in STANDALONE_PRODUCT_TYPES)
    catalog_ratio = round(1.0 - standalone / len(items), 4)
    category = next((it.category2 or it.category1 for it in items if it.category1), "")

    fields = {
        "product_name_ko": keyword,
        "category_naver": category or None,
        "price_naver": None,  # not priced yet (needs ALI cost); show market view instead
        "naver_catalog_lowest": _dec(catalog_lowest),
        "naver_price_min_market": _dec(price_min),
        "pricing_strategy": "catalog_match" if catalog_lowest else "standalone",
        # demand_score: log-scaled market size (real total result count) into 0..100
        "demand_score": _score(min(len(str(result.total)) * 14.0, 100.0)),
        "ops_cost_score": _score(catalog_ratio * 100.0),
        "priority_score": _score((1.0 - catalog_ratio) * 100.0),
        "status": "candidate",
    }

    ali_id = _pending_ali_id(keyword)
    existing = await repo.get_by_ali_id(ali_id)
    if existing is not None:
        await repo.update(existing.id, fields)
        return "updated"
    await repo.create({"ali_product_id": ali_id, **fields})
    return "created"


async def _run(args: argparse.Namespace) -> int:
    try:
        settings = get_settings()
    except Exception as exc:  # noqa: BLE001
        print(f"[config error] {exc}", file=sys.stderr)
        return 2

    shopping = NaverShoppingClient(settings.naver)
    counts = {"created": 0, "updated": 0, "empty": 0}
    try:
        async with get_db_session() as session:
            repo = ProductRepository(session)
            for keyword in args.keywords:
                outcome = await _seed_keyword(repo, shopping, keyword, args.display)
                counts[outcome] += 1
                print(f"  {keyword}: {outcome}")
    finally:
        await shopping.close()

    print(
        f"\nSeeded REAL Naver market data: {counts['created']} created, "
        f"{counts['updated']} updated, {counts['empty']} empty."
    )
    print("NOTE: ALI fields (price_ali, match) are NULL until valid ALI API creds are set.")
    return 0


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed DB with real Naver Shopping market data")
    p.add_argument(
        "keywords",
        nargs="*",
        default=["무선이어폰", "캠핑 의자", "강아지 장난감", "주방 정리함", "휴대용 선풍기"],
        help="Product keywords to fetch live market data for",
    )
    p.add_argument("--display", type=int, default=40, help="Results per keyword to aggregate")
    return p.parse_args()


def main() -> None:
    raise SystemExit(asyncio.run(_run(_parse_args())))


if __name__ == "__main__":
    main()
