#!/usr/bin/env python
"""
Dry-run fulfillment check: can each registered product actually be sourced?

Without placing any order, for each product this verifies:
  1. AliExpress side (DS): the stored itemId still resolves, is in stock, has a
     KRW price, and is shippable to KR (live freight) -> place_order WOULD work.
  2. Naver <-> AliExpress sameness: compares the Naver Shopping top result with
     the AliExpress product by title similarity (both Korean, no translation
     needed), shared spec tokens, image similarity (perceptual dHash), and price
     plausibility -> confidence that we'd order the SAME item the customer bought.

No LLM and no order placement -- read-only. Run against a seeded DB.

Usage:
    python scripts/check_fulfillment.py            # all registered/candidate
    python scripts/check_fulfillment.py --id 6
"""

import argparse
import asyncio
import re

from dropagent.clients.aliexpress import get_ali_client
from dropagent.clients.naver.shopping_api import NaverShoppingClient
from dropagent.config import get_settings
from dropagent.core.image_processor import make_image_scorer
from dropagent.core.matching.matcher import extract_spec_tokens, title_similarity
from dropagent.db.repositories.product_repo import ProductRepository
from dropagent.db.session import get_db_session

_TAG = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    return _TAG.sub("", text or "").strip()


async def _check_one(product, shopping, ali, scorer) -> dict:  # noqa: ANN001
    keyword = product.product_name_ko or product.product_name_en or ""
    out: dict = {"id": product.id, "keyword": keyword, "ali_id": product.ali_product_id}

    ali_id = product.ali_product_id or ""
    if not ali_id or ali_id.startswith("PENDING-"):
        out["verdict"] = "NO_ALI_MATCH (ali fields pending)"
        return out

    details = await ali.get_product_detail([ali_id])
    if not details:
        out["verdict"] = "ALI_NOT_FOUND (itemId no longer resolves)"
        return out
    d = details[0]
    in_stock = any((o.stock or 0) > 0 for o in d.options) if d.options else True
    out["ali_title"] = d.title
    out["ali_price"] = str(d.price.sale_price)
    out["in_stock"] = in_stock

    # shippable? live freight on the first sku
    sku_id = next((o.sku_id for o in d.options if o.sku_id), None)
    fee = None
    if sku_id:
        opts = await ali.query_freight(ali_id, sku_id)
        fee = str(opts[0].fee) if opts else None
    out["ship_fee"] = fee
    orderable = bool(d.price.sale_price > 0 and in_stock and fee is not None)

    # Naver <-> Ali sameness
    res = await shopping.search(query=keyword, display=5, sort="sim")
    nav = next((it for it in res.items if it.lowest_price > 0), None)
    same = {}
    if nav is not None:
        nav_title = _clean(nav.title)
        same["title_sim"] = round(title_similarity(nav_title, d.title), 3)
        specs_n, specs_a = extract_spec_tokens(nav_title), extract_spec_tokens(d.title)
        same["spec_overlap"] = sorted(specs_n & specs_a)
        img = await scorer(nav.image, d.image_url) if (nav.image and d.image_url) else None
        same["image_sim"] = round(img, 3) if img is not None else None
        same["naver_lprice"] = nav.lowest_price
        same["ali_krw"] = int(d.price.sale_price)
        # price ratio = ali / naver. The matcher treats (0.05, 0.8) as plausible:
        # a tiny ratio means the listings are almost certainly different products.
        same["price_ratio"] = round(int(d.price.sale_price) / nav.lowest_price, 4) if nav.lowest_price else None
    out["same"] = same

    # verdict: orderability (mechanism) + sameness (price ratio is the strongest
    # cheap signal; corroborated by title/image/spec).
    ts = same.get("title_sim", 0) or 0
    isim = same.get("image_sim") or 0
    ratio = same.get("price_ratio")
    plausible_ratio = ratio is not None and 0.05 <= ratio <= 0.8
    corroborated = ts >= 0.3 or isim >= 0.6 or bool(same.get("spec_overlap"))
    if plausible_ratio and corroborated:
        same_verdict = "SAME_PRODUCT~"
    elif ratio is not None and not plausible_ratio:
        same_verdict = "DIFFERENT_PRODUCT_LIKELY (price ratio off)"
    else:
        same_verdict = "SAMENESS_UNCERTAIN (run ProductMatcher to confirm)"
    out["verdict"] = (
        f"{'ORDERABLE' if orderable else 'NOT_ORDERABLE'} | {same_verdict} "
        f"(ratio {ratio}, title {ts}, image {same.get('image_sim')}, specs {same.get('spec_overlap')})"
    )
    return out


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    shopping = NaverShoppingClient(settings.naver)
    ali = get_ali_client(settings.aliexpress)
    scorer = make_image_scorer()
    print(f"AliExpress client: {type(ali).__name__}\n")
    try:
        async with get_db_session() as session:
            repo = ProductRepository(session)
            products = await repo.list_all(limit=50)
            if args.id:
                products = [p for p in products if p.id == args.id]
            if not products:
                print("No products. Seed first: python scripts/seed_real_naver.py")
                return 0
            for p in products:
                r = await _check_one(p, shopping, ali, scorer)
                print(f"[#{r['id']}] {r['keyword']}")
                if r.get("ali_title"):
                    print(f"   ALI: {r['ali_title'][:50]} | {r['ali_price']} KRW | "
                          f"stock={r['in_stock']} | ship={r.get('ship_fee')}")
                if r.get("same"):
                    s = r["same"]
                    print(f"   네이버 최상위: lprice={s.get('naver_lprice')} vs ALI={s.get('ali_krw')} KRW")
                print(f"   => {r['verdict']}\n")
    finally:
        await shopping.close()
        await ali.close()
    return 0


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Dry-run fulfillment / Naver<->Ali sameness check")
    p.add_argument("--id", type=int, default=None, help="Check only this product id")
    return p.parse_args()


def main() -> None:
    raise SystemExit(asyncio.run(_run(_parse_args())))


if __name__ == "__main__":
    main()
