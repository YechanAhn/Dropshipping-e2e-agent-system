"""Unit tests for the Naver Search Ad keyword-tool client."""

import base64
import hashlib
import hmac
from types import SimpleNamespace

import httpx
import pytest

from dropagent.clients.naver.auth import NaverSearchAdAuth
from dropagent.clients.naver.searchad_api import (
    MASKED_COUNT_VALUE,
    KeywordStat,
    NaverSearchAdClient,
    parse_count,
)

FAKE_SETTINGS = SimpleNamespace(api_key="ak", secret_key="sk", customer_id="123")


# --- parse_count -------------------------------------------------------------

def test_parse_count_integer():
    assert parse_count(1234) == (1234, False)


def test_parse_count_numeric_string_with_comma():
    assert parse_count("1,234") == (1234, False)


def test_parse_count_masked_under_ten():
    value, masked = parse_count("< 10")
    assert value == MASKED_COUNT_VALUE
    assert masked is True


def test_parse_count_invalid_string():
    assert parse_count("n/a") == (0, False)


# --- KeywordStat -------------------------------------------------------------

def test_keyword_stat_monthly_total():
    s = KeywordStat(keyword="무선이어폰", monthly_pc=300, monthly_mobile=700)
    assert s.monthly_total == 1000


# --- signature (HMAC) --------------------------------------------------------

def test_signature_matches_manual_hmac():
    auth = NaverSearchAdAuth(FAKE_SETTINGS)
    ts, method, uri = "1700000000000", "GET", "/keywordstool"
    expected = base64.b64encode(
        hmac.new(b"sk", f"{ts}.{method}.{uri}".encode(), hashlib.sha256).digest()
    ).decode()
    assert auth.generate_signature(ts, method, uri) == expected


def test_signature_is_deterministic():
    auth = NaverSearchAdAuth(FAKE_SETTINGS)
    a = auth.generate_signature("1", "GET", "/keywordstool")
    b = auth.generate_signature("1", "GET", "/keywordstool")
    assert a == b


def test_auth_headers_contain_required_fields():
    headers = NaverSearchAdAuth(FAKE_SETTINGS).get_auth_headers("GET", "/keywordstool")
    assert set(headers) == {"X-Timestamp", "X-API-KEY", "X-Customer", "X-Signature"}
    assert headers["X-API-KEY"] == "ak"
    assert headers["X-Customer"] == "123"


# --- client.get_keyword_stats ------------------------------------------------

def _mock_client(payload: dict) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_get_keyword_stats_parses_list_and_masking():
    payload = {
        "keywordList": [
            {
                "relKeyword": "무선이어폰",
                "monthlyPcQcCnt": 12000,
                "monthlyMobileQcCnt": 48000,
                "compIdx": "높음",
                "plAvgDepth": 15,
            },
            {
                "relKeyword": "희귀키워드",
                "monthlyPcQcCnt": "< 10",
                "monthlyMobileQcCnt": "< 10",
                "compIdx": "낮음",
            },
        ]
    }
    client = NaverSearchAdClient(settings=FAKE_SETTINGS, http_client=_mock_client(payload))
    stats = await client.get_keyword_stats(["무선이어폰"])

    assert len(stats) == 2
    assert stats[0].keyword == "무선이어폰"
    assert stats[0].monthly_total == 60000
    assert stats[0].is_masked is False
    assert stats[1].is_masked is True
    assert stats[1].monthly_total == 2 * MASKED_COUNT_VALUE


async def test_get_keyword_stats_rejects_too_many_hints():
    client = NaverSearchAdClient(settings=FAKE_SETTINGS, http_client=_mock_client({"keywordList": []}))
    with pytest.raises(ValueError):
        await client.get_keyword_stats(["a", "b", "c", "d", "e", "f"])


async def test_get_keyword_stats_empty_input():
    client = NaverSearchAdClient(settings=FAKE_SETTINGS, http_client=_mock_client({"keywordList": []}))
    assert await client.get_keyword_stats([]) == []
