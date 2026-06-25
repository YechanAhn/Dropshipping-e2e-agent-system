"""
Throwaway live probe: determine which Naver DataLab endpoint serves a
category-free keyword trend (for the §4.1 momentum provider).

NOT part of the app. Run manually once NAVER_CLIENT_ID / NAVER_CLIENT_SECRET
are available, then delete (or keep under scripts/ as an ops check).

Usage:
    # creds via .env (NAVER_CLIENT_ID, NAVER_CLIENT_SECRET) or shell env
    python scripts/_probe_datalab.py [keyword] [category_cid]

It hits THREE endpoints with one real keyword and prints HTTP status +
the parsed shape, so we can confirm the correct momentum source:

  A) /v1/datalab/search                     (통합검색어 트렌드, keywordGroups, NO category)
  B) /v1/datalab/shopping                    (the path the current code uses — expected to fail)
  C) /v1/datalab/shopping/category/keywords  (쇼핑인사이트 키워드별, REQUIRES category cid)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx


def _load_dotenv() -> None:
    """Minimal .env loader (no dependency) so the probe is self-contained."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


def _headers() -> dict[str, str]:
    cid = os.environ.get("NAVER_CLIENT_ID", "")
    secret = os.environ.get("NAVER_CLIENT_SECRET", "")
    if not cid or not secret:
        sys.exit(
            "MISSING CREDS: set NAVER_CLIENT_ID and NAVER_CLIENT_SECRET in .env "
            "or the shell. (Issue free keys at https://developers.naver.com)"
        )
    return {
        "X-Naver-Client-Id": cid,
        "X-Naver-Client-Secret": secret,
        "Content-Type": "application/json",
    }


async def _probe(client: httpx.AsyncClient, name: str, url: str, payload: dict) -> None:
    print(f"\n{'=' * 70}\n[{name}]\n  POST {url}\n  body: {json.dumps(payload, ensure_ascii=False)}")
    try:
        r = await client.post(url, json=payload, headers=_headers(), timeout=15.0)
    except Exception as exc:  # noqa: BLE001
        print(f"  -> network error: {exc!r}")
        return
    print(f"  -> HTTP {r.status_code}")
    if r.status_code != 200:
        print(f"  -> body: {r.text[:500]}")
        return
    data = r.json()
    results = data.get("results", [])
    print(f"  -> results groups: {len(results)}")
    if results:
        g = results[0]
        pts = g.get("data", [])
        print(f"  -> group keys: {list(g.keys())}")
        print(f"  -> data points: {len(pts)}; first: {pts[0] if pts else None}; last: {pts[-1] if pts else None}")
        ratios = [p.get("ratio") for p in pts][:6]
        print(f"  -> ratios[:6]: {ratios}")


async def main() -> None:
    _load_dotenv()
    keyword = sys.argv[1] if len(sys.argv) > 1 else "무선이어폰"
    category = sys.argv[2] if len(sys.argv) > 2 else "50000008"  # 디지털/가전 (example cid)

    end = date.today()
    start = end - timedelta(weeks=56)
    sd, ed = start.isoformat(), end.isoformat()

    async with httpx.AsyncClient() as client:
        # A) 통합검색어 트렌드 — keywordGroups, category-free (the hypothesis: THIS is correct)
        await _probe(
            client,
            "A: search trend  /v1/datalab/search  (keywordGroups, no category)",
            "https://openapi.naver.com/v1/datalab/search",
            {
                "startDate": sd,
                "endDate": ed,
                "timeUnit": "week",
                "keywordGroups": [{"groupName": keyword, "keywords": [keyword]}],
            },
        )

        # B) what the current code does — keyword/name/param to /shopping (expected: fail)
        await _probe(
            client,
            "B: current code  /v1/datalab/shopping  (keyword name/param, no category)",
            "https://openapi.naver.com/v1/datalab/shopping",
            {
                "startDate": sd,
                "endDate": ed,
                "timeUnit": "week",
                "keyword": [{"name": keyword, "param": [keyword]}],
            },
        )

        # C) shopping insight keyword trend — REQUIRES category cid
        await _probe(
            client,
            f"C: shopping kw   /v1/datalab/shopping/category/keywords  (category={category})",
            "https://openapi.naver.com/v1/datalab/shopping/category/keywords",
            {
                "startDate": sd,
                "endDate": ed,
                "timeUnit": "week",
                "category": category,
                "keyword": [{"name": keyword, "param": [keyword]}],
            },
        )

    print(f"\n{'=' * 70}\nVERDICT: the endpoint returning HTTP 200 with results[0].data[].ratio")
    print("is the correct momentum source. Expectation: A succeeds (category-free),")
    print("B fails (wrong path/shape), C succeeds only with a valid category cid.")


if __name__ == "__main__":
    asyncio.run(main())
