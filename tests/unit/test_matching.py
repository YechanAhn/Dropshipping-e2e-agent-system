"""
Unit tests for the product matching engine.

All external dependencies (AliExpress client, translator, verifier) are
faked so the suite runs with no network access and no LLM/API keys.  The
fakes implement just the small surface the matcher relies on:

    - ali_client.search_products(keywords, *, page_size) -> object with
      ``.products`` (each product exposes ``.title`` and ``.price.sale_price``).
    - translator(naver) -> English query string.
    - verifier(naver, ali_product) -> (confidence, reason).
"""

from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from dropagent.core.matching import (
    MatchStatus,
    NaverProductRef,
    ProductMatcher,
    extract_spec_tokens,
    title_similarity,
)

# =====================================================================
# Test doubles (no network, no LLM)
# =====================================================================


@dataclass
class FakePrice:
    """Minimal stand-in for ``AliPriceInfo`` exposing ``sale_price``."""

    sale_price: Decimal


@dataclass
class FakeAliProduct:
    """Minimal stand-in for ``AliProduct`` used by the matcher."""

    product_id: str
    title: str
    price: FakePrice
    image_url: str = ""


@dataclass
class FakeSearchResult:
    """Minimal stand-in for ``AliSearchResult`` (only ``.products`` is read)."""

    products: list[FakeAliProduct] = field(default_factory=list)


class FakeAliClient:
    """Async AliExpress client returning a fixed product list."""

    def __init__(self, products: list[FakeAliProduct]) -> None:
        self._products = products
        self.last_keywords: str | None = None
        self.last_page_size: int | None = None

    async def search_products(self, keywords: str, *, page_size: int = 50) -> FakeSearchResult:
        """Record the query and return the pre-seeded products."""
        self.last_keywords = keywords
        self.last_page_size = page_size
        return FakeSearchResult(products=list(self._products))


def make_product(product_id: str, title: str, usd: str) -> FakeAliProduct:
    """Build a fake AliExpress product with a USD sale price."""
    return FakeAliProduct(
        product_id=product_id,
        title=title,
        price=FakePrice(sale_price=Decimal(usd)),
        image_url=f"https://img.example/{product_id}.jpg",
    )


def constant_translator(query: str):
    """Return an async translator that always yields ``query``."""

    async def _translate(naver: NaverProductRef) -> str:
        return query

    return _translate


def constant_verifier(confidence: float, reason: str = "fake"):
    """Return an async verifier that always yields ``(confidence, reason)``."""

    async def _verify(naver: NaverProductRef, ali_product: object) -> tuple[float, str]:
        return confidence, reason

    return _verify


# =====================================================================
# title_similarity
# =====================================================================


class TestTitleSimilarity:
    """Cheap token-overlap (Jaccard) similarity helper."""

    def test_identical_is_one(self):
        assert title_similarity("LED Ring Light Stand", "LED Ring Light Stand") == 1.0

    def test_identical_ignores_case_and_order(self):
        assert title_similarity("LED Ring Light", "light ring led") == 1.0

    def test_disjoint_is_zero(self):
        assert title_similarity("alpha beta gamma", "delta epsilon zeta") == 0.0

    def test_partial_overlap_between_zero_and_one(self):
        # {led, ring, light} vs {led, ring, stand} -> 2 / 4 = 0.5
        score = title_similarity("LED Ring Light", "LED Ring Stand")
        assert score == pytest.approx(0.5)
        assert 0.0 < score < 1.0

    def test_empty_strings_are_zero(self):
        assert title_similarity("", "") == 0.0
        assert title_similarity("led ring", "") == 0.0

    def test_punctuation_does_not_break_tokens(self):
        # Non-alphanumeric chars are stripped; tokens still match.
        assert title_similarity("LED-Ring, Light!", "led ring light") == 1.0


# =====================================================================
# ProductMatcher.match
# =====================================================================


@pytest.fixture
def naver():
    """A trending Naver product priced at 30,000 KRW."""
    return NaverProductRef(
        title_ko="LED 링라이트 삼각대",
        price=30_000,
        image_url="https://naver.example/ringlight.jpg",
        category="디지털/가전",
    )


async def test_auto_match(naver):
    """A plausible cheaper product + high verifier confidence -> AUTO."""
    # 10 USD * 1350 / 30000 = 0.45 -> within (0.05, 0.8).
    products = [make_product("A1", "LED Ring Light Tripod Stand", "10.00")]
    matcher = ProductMatcher(
        FakeAliClient(products),
        translator=constant_translator("LED Ring Light Tripod Stand"),
        verifier=constant_verifier(0.9, "same item"),
    )

    result = await matcher.match(naver)

    assert result.status == MatchStatus.AUTO
    assert result.query_en == "LED Ring Light Tripod Stand"
    assert result.best is not None
    assert result.best.ali_product.product_id == "A1"
    assert result.best.confidence == pytest.approx(0.9)
    assert result.best.reason == "same item"
    assert result.best.price_ratio == pytest.approx(0.45)
    assert len(result.candidates) == 1


async def test_review_band(naver):
    """Mid confidence (>= review, < auto) -> REVIEW with a best candidate."""
    products = [make_product("R1", "LED Ring Light Tripod Stand", "10.00")]
    matcher = ProductMatcher(
        FakeAliClient(products),
        translator=constant_translator("LED Ring Light Tripod Stand"),
        verifier=constant_verifier(0.7, "probably"),
    )

    result = await matcher.match(naver)

    assert result.status == MatchStatus.REVIEW
    assert result.best is not None
    assert result.best.confidence == pytest.approx(0.7)


async def test_reject_when_all_priced_implausibly(naver):
    """All candidates more expensive than Naver (price_ratio > bounds) -> REJECT."""
    # 30 USD * 1350 / 30000 = 1.35 -> above the 0.8 upper bound.
    products = [
        make_product("X1", "LED Ring Light Tripod Stand", "30.00"),
        make_product("X2", "LED Ring Light Tripod Stand", "50.00"),
    ]
    matcher = ProductMatcher(
        FakeAliClient(products),
        translator=constant_translator("LED Ring Light Tripod Stand"),
        # Verifier would say AUTO, but nothing should reach it.
        verifier=constant_verifier(0.99, "should not be used"),
    )

    result = await matcher.match(naver)

    assert result.status == MatchStatus.REJECT
    assert result.best is None
    assert result.candidates == []


def mapping_image_scorer(by_ali_url: dict[str, float | None]):
    """An async image scorer keyed by the AliExpress image URL."""

    async def _score(naver_url: str, ali_url: str) -> float | None:
        return by_ali_url.get(ali_url)

    return _score


# =====================================================================
# Image re-rank + spec-token identity locks
# =====================================================================


async def test_no_image_scorer_leaves_similarity_none(naver):
    """Default (no scorer): image_similarity stays None, title ranking unchanged."""
    products = [make_product("A1", "LED Ring Light Tripod Stand", "10.00")]
    matcher = ProductMatcher(
        FakeAliClient(products),
        translator=constant_translator("LED Ring Light Tripod Stand"),
        verifier=constant_verifier(0.9, "same item"),
    )

    result = await matcher.match(naver)

    assert result.best is not None
    assert result.best.image_similarity is None


async def test_image_scorer_reranks_shortlist(naver):
    """A high-photo-similarity but low-title product wins once images are scored."""
    products = [
        make_product("HIGH_TITLE", "LED Ring Light Tripod Stand", "10.00"),  # title 1.0
        make_product("HIGH_IMAGE", "lamp", "10.00"),                          # title ~0.0
    ]
    scorer = mapping_image_scorer(
        {
            "https://img.example/HIGH_TITLE.jpg": 0.10,
            "https://img.example/HIGH_IMAGE.jpg": 0.95,
        }
    )
    matcher = ProductMatcher(
        FakeAliClient(products),
        translator=constant_translator("LED Ring Light Tripod Stand"),
        verifier=constant_verifier(0.9, "same item"),
        image_scorer=scorer,
    )

    result = await matcher.match(naver, top_k=1)

    assert result.best is not None
    assert result.best.ali_product.product_id == "HIGH_IMAGE"
    assert result.best.image_similarity == 0.95


async def test_image_scorer_populates_similarity_field(naver):
    """Every plausible candidate gets its image_similarity recorded."""
    products = [make_product("A1", "LED Ring Light Tripod Stand", "10.00")]
    scorer = mapping_image_scorer({"https://img.example/A1.jpg": 0.8})
    matcher = ProductMatcher(
        FakeAliClient(products),
        translator=constant_translator("LED Ring Light Tripod Stand"),
        verifier=constant_verifier(0.9, "same item"),
        image_scorer=scorer,
    )

    result = await matcher.match(naver)

    assert result.best is not None
    assert result.best.image_similarity == 0.8


async def test_require_spec_match_drops_mismatched_models():
    """With require_spec_match, only candidates sharing a spec token survive."""
    naver = NaverProductRef(title_ko="보조배터리 20000mah 대용량", price=30_000)
    products = [
        make_product("SAME", "Power Bank 20000mAh Fast Charge", "10.00"),
        make_product("OTHER", "Power Bank 10000mAh Mini", "10.00"),
    ]
    matcher = ProductMatcher(
        FakeAliClient(products),
        translator=constant_translator("power bank 20000mah"),
        verifier=constant_verifier(0.9, "same item"),
    )

    result = await matcher.match(naver, require_spec_match=True)

    assert result.status == MatchStatus.AUTO
    assert len(result.candidates) == 1
    assert result.candidates[0].ali_product.product_id == "SAME"


async def test_reject_on_low_confidence(naver):
    """A price-plausible product but low verifier confidence -> REJECT."""
    products = [make_product("L1", "LED Ring Light Tripod Stand", "10.00")]
    matcher = ProductMatcher(
        FakeAliClient(products),
        translator=constant_translator("LED Ring Light Tripod Stand"),
        verifier=constant_verifier(0.2, "different item"),
    )

    result = await matcher.match(naver)

    assert result.status == MatchStatus.REJECT
    # Below review threshold, but the candidate was still evaluated.
    assert result.best is not None
    assert result.best.confidence == pytest.approx(0.2)


async def test_price_ratio_filtering_excludes_implausible(naver):
    """Only the price-plausible product survives the coarse filter."""
    products = [
        make_product("TOO_EXPENSIVE", "LED Ring Light Tripod Stand", "30.00"),  # ratio 1.35
        make_product("PLAUSIBLE", "LED Ring Light Tripod Stand", "10.00"),  # ratio 0.45
        make_product("TOO_CHEAP", "LED Ring Light Tripod Stand", "0.50"),  # ratio 0.0225
    ]
    matcher = ProductMatcher(
        FakeAliClient(products),
        translator=constant_translator("LED Ring Light Tripod Stand"),
        verifier=constant_verifier(0.9, "same item"),
    )

    result = await matcher.match(naver)

    assert result.status == MatchStatus.AUTO
    assert len(result.candidates) == 1
    assert result.candidates[0].ali_product.product_id == "PLAUSIBLE"
    assert result.best is not None
    assert result.best.ali_product.product_id == "PLAUSIBLE"


async def test_top_k_limits_verified_candidates(naver):
    """Only ``top_k`` price-plausible products are shortlisted and verified."""
    # All four are price-plausible (10 USD -> ratio 0.45).  Distinct titles so
    # title_similarity ranks them; top_k=2 keeps the two closest to the query.
    products = [
        make_product("P1", "LED Ring Light Tripod Stand", "10.00"),
        make_product("P2", "LED Ring Light Tripod", "10.00"),
        make_product("P3", "LED Ring Light", "10.00"),
        make_product("P4", "Ring", "10.00"),
    ]
    matcher = ProductMatcher(
        FakeAliClient(products),
        translator=constant_translator("LED Ring Light Tripod Stand"),
        verifier=constant_verifier(0.9, "same item"),
    )

    result = await matcher.match(naver, top_k=2)

    assert len(result.candidates) == 2
    kept_ids = {c.ali_product.product_id for c in result.candidates}
    assert kept_ids == {"P1", "P2"}


async def test_empty_search_results_reject(naver):
    """No AliExpress results at all -> REJECT with no best candidate."""
    matcher = ProductMatcher(
        FakeAliClient([]),
        translator=constant_translator("LED Ring Light Tripod Stand"),
        verifier=constant_verifier(0.9, "unused"),
    )

    result = await matcher.match(naver)

    assert result.status == MatchStatus.REJECT
    assert result.best is None
    assert result.candidates == []


async def test_translator_query_is_used_for_search(naver):
    """The translated query is what gets sent to the AliExpress client."""
    client = FakeAliClient([make_product("A1", "LED Ring Light Tripod Stand", "10.00")])
    matcher = ProductMatcher(
        client,
        translator=constant_translator("led ring light tripod"),
        verifier=constant_verifier(0.9, "same item"),
    )

    result = await matcher.match(naver, page_size=17)

    assert client.last_keywords == "led ring light tripod"
    assert client.last_page_size == 17
    assert result.query_en == "led ring light tripod"


async def test_custom_fx_rate_changes_plausibility(naver):
    """A different FX rate shifts which products are price-plausible."""
    # At 10 USD with fx 100: ratio = 1000 / 30000 = 0.033 -> below 0.05 bound,
    # so the otherwise-good product is filtered out and the result is REJECT.
    products = [make_product("A1", "LED Ring Light Tripod Stand", "10.00")]
    matcher = ProductMatcher(
        FakeAliClient(products),
        translator=constant_translator("LED Ring Light Tripod Stand"),
        verifier=constant_verifier(0.9, "same item"),
        fx_rate=100.0,
    )

    result = await matcher.match(naver)

    assert result.status == MatchStatus.REJECT
    assert result.best is None


class TestExtractSpecTokens:
    """Model/spec token extraction (alphanumerics containing a digit)."""

    def test_extracts_capacity_and_skips_non_digit_tokens(self):
        assert extract_spec_tokens("Power Bank 20000mAh Type-C") == {"20000mah"}

    def test_extracts_model_number_keeps_hyphen(self):
        # Hyphenated model numbers stay intact so WH-1000XM5 != WF-1000XM5.
        assert extract_spec_tokens("JR-T03 Bluetooth Earbuds") == {"jr-t03"}
        assert extract_spec_tokens("Sony WH-1000XM5 vs WF-1000XM5") == {
            "wh-1000xm5",
            "wf-1000xm5",
        }

    def test_extracts_multiple_specs(self):
        assert extract_spec_tokens("4K Action Cam 64GB") == {"4k", "64gb"}

    def test_no_specs_returns_empty(self):
        assert extract_spec_tokens("ring light tripod stand") == set()
