#!/usr/bin/env python
"""
Refresh the AliExpress DS access_token and persist it to .env.

The DS access_token expires in ~24h; the refresh_token lasts longer. Run this
(e.g. via cron, daily) to keep the credentials live. Uses the refresh_token in
.env, calls /rest/auth/token/refresh, and writes the rotated
ALI_ACCESS_TOKEN / ALI_REFRESH_TOKEN / ALI_TOKEN_EXPIRE_AT back to .env.

Secrets are never printed.

Usage:
    python scripts/refresh_ali_token.py
"""

import asyncio
import re
import sys

from dropagent.clients.aliexpress import AliExpressDSClient
from dropagent.config import get_settings

ENV_PATH = ".env"


def _write_env(updates: dict[str, str]) -> None:
    lines = open(ENV_PATH, encoding="utf-8").read().splitlines()
    seen: set[str] = set()
    for i, line in enumerate(lines):
        for key, value in updates.items():
            if re.match(rf"\s*{key}\s*=", line):
                lines[i] = f"{key}={value}"
                seen.add(key)
    for key, value in updates.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    open(ENV_PATH, "w", encoding="utf-8").write("\n".join(lines) + "\n")


async def _run() -> int:
    settings = get_settings().aliexpress
    if not settings.refresh_token:
        print("[error] ALI_REFRESH_TOKEN not set in .env", file=sys.stderr)
        return 2

    client = AliExpressDSClient(settings)
    try:
        data = await client.refresh_access_token()
    finally:
        await client.close()

    updates = {
        "ALI_ACCESS_TOKEN": str(data["access_token"]),
        "ALI_TOKEN_EXPIRE_AT": str(data.get("expire_time", "")),
    }
    if data.get("refresh_token"):
        updates["ALI_REFRESH_TOKEN"] = str(data["refresh_token"])
    _write_env(updates)

    print("AliExpress DS token refreshed and written to .env (secrets not shown).")
    print(f"  expire_time={data.get('expire_time')} refresh_present={bool(data.get('refresh_token'))}")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
