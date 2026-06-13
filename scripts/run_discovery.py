#!/usr/bin/env python
"""
Run the demand-first discovery pipeline on seed keywords and print the Top-N.

This is the tangible Phase-1 entry point: it expands seeds via the Naver Search
Ad keyword tool (absolute demand), measures supply/competition via Naver
Shopping, scores opportunities, and prints a ranked table.

Requires live credentials in ``.env`` (NAVER_SEARCHAD_* and NAVER_CLIENT_*) and
outbound network access.

Usage:
    python scripts/run_discovery.py 무선이어폰 차량용거치대 --top 15
    python scripts/run_discovery.py 캠핑 --min-volume 2000 --max-competition 2.0
"""

import argparse
import asyncio
import sys

from dropagent.clients.naver.searchad_api import NaverSearchAdClient
from dropagent.clients.naver.shopping_api import NaverShoppingClient
from dropagent.config import get_settings
from dropagent.pipeline.discovery import DiscoveryPipeline


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Demand-first opportunity discovery")
    p.add_argument("seeds", nargs="+", help="Seed keywords / categories to expand from")
    p.add_argument("--top", type=int, default=20, help="Number of opportunities to print")
    p.add_argument("--min-volume", type=int, default=1000, help="Min monthly search volume")
    p.add_argument("--max-competition", type=float, default=3.0, help="Max 경쟁강도 (상품수/검색량)")
    p.add_argument("--max-candidates", type=int, default=200, help="Cap on expanded candidates")
    return p.parse_args()


async def _run(args: argparse.Namespace) -> int:
    try:
        settings = get_settings()
    except Exception as exc:  # noqa: BLE001 - surface config errors helpfully
        print(f"[config error] {exc}\n-> Copy .env.example to .env and fill credentials.", file=sys.stderr)
        return 2

    searchad = NaverSearchAdClient(settings.searchad)
    shopping = NaverShoppingClient(settings.naver)
    pipeline = DiscoveryPipeline(searchad, shopping)

    try:
        results = await pipeline.discover(
            args.seeds,
            min_monthly_volume=args.min_volume,
            max_competition=args.max_competition,
            max_candidates=args.max_candidates,
            top_n=args.top,
        )
    finally:
        await searchad.close()
        await shopping.close()

    if not results:
        print("No opportunities found (try lowering --min-volume / raising --max-competition).")
        return 0

    header = (
        f"{'#':>2}  {'keyword':<24} {'검색량':>8} {'상품수':>9} {'경쟁강도':>7} "
        f"{'등급':<6} {'카탈로그':>7} {'중앙가':>8} {'기회':>5}"
    )
    print(header)
    print("-" * len(header))
    for i, c in enumerate(results, 1):
        masked = "*" if c.volume_masked else " "
        print(
            f"{i:>2}  {c.keyword[:24]:<24} {c.monthly_volume:>7}{masked} {c.product_count:>9} "
            f"{c.competition:>7.2f} {c.grade_ko:<6} {c.catalog_ratio:>7.0%} "
            f"{c.price_median:>8} {c.opportunity:>5.2f}"
        )
    print("\n* = 검색량이 '< 10'으로 마스킹된 키워드 (저수요)")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run(_parse_args())))


if __name__ == "__main__":
    main()
