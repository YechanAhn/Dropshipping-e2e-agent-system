"""
Product matching engine.

Links a trending Naver product to the *same* item on AliExpress.  Because the
two marketplaces share no common identifier, matching is a multi-stage
pipeline:

    1. translate   - Korean title -> English search query (LLM-backed by default)
    2. search      - keyword search against the AliExpress Affiliate API
    3. coarse filter - price plausibility (AliExpress must be meaningfully
                       cheaper than Naver) + cheap title similarity
    4. shortlist   - keep the top-K candidates by title similarity
    5. verify      - per-candidate LLM confidence on the shortlist
    6. decide      - threshold the best confidence into auto / review / reject

Every external dependency (AliExpress client, translator, verifier) is
dependency-injected.  The defaults are LLM-backed and built lazily so that
constructing a :class:`ProductMatcher` never requires API keys; tests inject
fakes and never touch the network.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

from dropagent.utils.logging import get_logger

from .models import MatchCandidate, MatchResult, MatchStatus, NaverProductRef

logger = get_logger(__name__)

# A translator turns a Naver product reference into an English search query.
Translator = Callable[[NaverProductRef], Awaitable[str]]

# A verifier compares a Naver product against an AliExpress product and returns
# ``(confidence in 0..1, human-readable reason)``.
Verifier = Callable[[NaverProductRef, object], Awaitable[tuple[float, str]]]

# An image scorer compares two image URLs and returns a 0..1 similarity (or
# ``None`` when it cannot be computed). See ``core.image_processor``.
ImageScorer = Callable[[str, str], Awaitable["float | None"]]

# Default USD -> KRW conversion used when none is supplied.
DEFAULT_FX_RATE = 1350.0

_TOKEN_RE = re.compile(r"[a-z0-9]+")
# A spec/model token is an alphanumeric token containing at least one digit
# (model numbers like 'jr-t03', capacities like '20000mah', '500ml', '4k').
_SPEC_TOKEN_RE = re.compile(r"[a-z0-9]*\d[a-z0-9]*")


def _tokenize(text: str) -> set[str]:
    """Lowercase ``text`` and split it into a set of alphanumeric tokens."""
    return set(_TOKEN_RE.findall(text.lower()))


def extract_spec_tokens(text: str) -> set[str]:
    """
    Extract model/spec tokens (alphanumerics containing a digit) from a title.

    These are strong product-identity locks -- e.g. '20000mah', 'jr-t03', '4k'
    -- that survive KO->EN translation, so a shared spec token between a Naver
    and an AliExpress title is high-precision evidence of the same SKU.
    """
    return set(_SPEC_TOKEN_RE.findall(text.lower()))


def title_similarity(a: str, b: str) -> float:
    """
    Compute a cheap token-overlap (Jaccard) similarity between two titles.

    Both strings are lowercased and split into alphanumeric tokens; the score
    is ``|A ∩ B| / |A ∪ B|``.  This is pure, deterministic, and fast — used as
    a coarse filter before the (expensive) LLM verification step.

    Args:
        a: First title.
        b: Second title.

    Returns:
        Similarity in ``[0.0, 1.0]``.  Identical token sets return ``1.0``;
        fully disjoint sets return ``0.0``.  Two empty strings return ``0.0``.
    """
    tokens_a = _tokenize(a)
    tokens_b = _tokenize(b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


class ProductMatcher:
    """
    Match a Naver product to the same item on AliExpress.

    Args:
        ali_client: AliExpress client exposing
            ``async search_products(keywords, *, page_size=...) -> result`` where
            the result has a ``.products`` list of products carrying ``title`` and
            ``price.sale_price`` (USD ``Decimal``).
        translator: Optional KO-title -> EN-query coroutine.  Defaults to an
            LLM-backed translator built lazily on first use.
        verifier: Optional ``(naver, ali_product) -> (confidence, reason)``
            coroutine.  Defaults to an LLM-backed comparison built lazily.
        image_scorer: Optional ``(naver_image_url, ali_image_url) -> 0..1|None``
            coroutine (e.g. ``core.image_processor.make_image_scorer()``).  When
            given, price-plausible candidates are re-ranked by photo similarity
            before shortlisting, narrowing a broad title match to the same SKU.
            Defaults to ``None`` (title-similarity ranking only, no network).
        fx_rate: USD -> KRW rate used to convert AliExpress sale prices for the
            price-ratio plausibility check.
    """

    def __init__(
        self,
        ali_client: Any,
        *,
        translator: Translator | None = None,
        verifier: Verifier | None = None,
        image_scorer: ImageScorer | None = None,
        fx_rate: float = DEFAULT_FX_RATE,
    ) -> None:
        self._ali_client = ali_client
        self._translator = translator
        self._verifier = verifier
        self._image_scorer = image_scorer
        self._fx_rate = fx_rate
        # Lazily-constructed LLM router shared by the default impls so we only
        # ever build (and key-check) it once, and never at construction time.
        self._router: Any | None = None

    # ------------------------------------------------------------------
    # Lazy default dependencies (LLM-backed; never required at construction)
    # ------------------------------------------------------------------

    def _get_router(self) -> Any:
        """Build (once) and return the default :class:`LLMRouter`."""
        if self._router is None:
            from dropagent.clients.llm.router import LLMRouter

            self._router = LLMRouter()
        return self._router

    def _get_translator(self) -> Translator:
        """Return the configured translator, or a lazily-built LLM default."""
        if self._translator is not None:
            return self._translator

        async def _default_translate(naver: NaverProductRef) -> str:
            """Translate a Korean title to an English AliExpress search query."""
            router = self._get_router()
            prompt = (
                "Translate the following Korean e-commerce product title into a "
                "concise English search query suitable for AliExpress. Return only "
                "the query, no quotes or extra text.\n"
                f"Category: {naver.category or 'unknown'}\n"
                f"Title: {naver.title_ko}"
            )
            query = await router.route("translation", prompt)
            return query.strip()

        self._translator = _default_translate
        return self._translator

    def _get_verifier(self) -> Verifier:
        """Return the configured verifier, or a lazily-built LLM default."""
        if self._verifier is not None:
            return self._verifier

        async def _default_verify(naver: NaverProductRef, ali_product: object) -> tuple[float, str]:
            """Ask the LLM whether the two listings are the same product."""
            router = self._get_router()
            ali_title = getattr(ali_product, "title", "")
            prompt = (
                "You compare two e-commerce listings and judge whether they are "
                "the SAME physical product. Respond with a confidence score "
                "between 0 and 1 followed by a short reason, formatted exactly as "
                "'<score>|<reason>'.\n"
                f"Naver (Korean): {naver.title_ko}\n"
                f"AliExpress (English): {ali_title}"
            )
            raw = await router.route("category_match", prompt)
            return _parse_verifier_response(raw)

        self._verifier = _default_verify
        return self._verifier

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def match(
        self,
        naver: NaverProductRef,
        *,
        top_k: int = 5,
        page_size: int = 30,
        auto_threshold: float = 0.85,
        review_threshold: float = 0.6,
        price_ratio_bounds: tuple[float, float] = (0.05, 0.8),
        require_spec_match: bool = False,
    ) -> MatchResult:
        """
        Find the AliExpress product that best matches ``naver``.

        Args:
            naver: The trending Naver product to match.
            top_k: Number of candidates (by title similarity) to verify.
            page_size: AliExpress search page size.
            auto_threshold: Minimum best confidence to auto-accept.
            review_threshold: Minimum best confidence to route to human review.
            price_ratio_bounds: Inclusive ``(low, high)`` bounds on
                ``ali_price_krw / naver_price``.  AliExpress must be meaningfully
                cheaper than Naver, so plausible matches fall below ``high``;
                anything outside the band is treated as implausible and dropped.
            require_spec_match: When the Naver title carries model/spec tokens
                (e.g. '20000mah', 'jr-t03'), drop candidates whose title shares
                none of them.  High-precision identity lock; off by default to
                preserve recall.

        Returns:
            A :class:`MatchResult` with the decision, query, best candidate, and
            all verified candidates.
        """
        translator = self._get_translator()
        verifier = self._get_verifier()

        # 1. Translate Korean title -> English query.
        query_en = (await translator(naver)).strip()

        # 2. Keyword search on AliExpress.
        search = await self._ali_client.search_products(query_en, page_size=page_size)
        products = list(getattr(search, "products", []) or [])

        logger.info(
            "matching_search_complete",
            query_en=query_en,
            result_count=len(products),
        )

        # 3. Coarse filter: keep only price-plausible (and, optionally,
        #    spec-matching) products.
        low, high = price_ratio_bounds
        query_for_similarity = query_en or naver.title_ko
        naver_specs = extract_spec_tokens(naver.title_ko) if require_spec_match else set()
        plausible: list[MatchCandidate] = []
        for product in products:
            price_ratio = self._price_ratio(product, naver.price)
            if price_ratio is None or not (low <= price_ratio <= high):
                continue
            ali_title = getattr(product, "title", "")
            if naver_specs and not (naver_specs & extract_spec_tokens(ali_title)):
                continue
            similarity = title_similarity(query_for_similarity, ali_title)
            plausible.append(
                MatchCandidate(
                    ali_product=product,
                    title_similarity=similarity,
                    price_ratio=price_ratio,
                )
            )

        # No plausible candidate -> reject early.
        if not plausible:
            logger.info("matching_no_plausible_candidate", query_en=query_en)
            return MatchResult(status=MatchStatus.REJECT, query_en=query_en, best=None, candidates=[])

        # 3b. Optional image re-rank: score each candidate's photo against the
        #     Naver photo so the shortlist is "same photo", not just same words.
        if self._image_scorer is not None and naver.image_url:
            scores = await asyncio.gather(
                *(
                    self._image_scorer(naver.image_url, getattr(c.ali_product, "image_url", ""))
                    for c in plausible
                )
            )
            for candidate, score in zip(plausible, scores, strict=True):
                candidate.image_similarity = score

        # 4. Shortlist the top-K, image-aware when available (fall back to title).
        shortlist = sorted(plausible, key=self._rank_key, reverse=True)[:top_k]

        # 5. Verify each shortlisted candidate.
        for candidate in shortlist:
            confidence, reason = await verifier(naver, candidate.ali_product)
            candidate.confidence = float(confidence)
            candidate.reason = reason

        # 6. Decide based on the best confidence.
        best = max(shortlist, key=lambda c: c.confidence)
        status = self._classify(best.confidence, auto_threshold, review_threshold)

        logger.info(
            "matching_decision",
            query_en=query_en,
            status=status.value,
            best_confidence=best.confidence,
            candidate_count=len(shortlist),
        )

        return MatchResult(status=status, query_en=query_en, best=best, candidates=shortlist)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _price_ratio(self, product: Any, naver_price: int) -> float | None:
        """
        Compute ``ali_price_krw / naver_price`` for ``product``.

        Returns ``None`` when the ratio cannot be computed (missing price or a
        non-positive Naver price), so callers can treat it as implausible.
        """
        if naver_price <= 0:
            return None
        try:
            sale_price_usd = Decimal(str(product.price.sale_price))
        except (AttributeError, TypeError, ValueError):
            return None
        ali_price_krw = float(sale_price_usd) * self._fx_rate
        return ali_price_krw / naver_price

    @staticmethod
    def _rank_key(candidate: MatchCandidate) -> tuple[float, float]:
        """Rank by photo similarity when scored, else title; title breaks ties."""
        primary = (
            candidate.image_similarity
            if candidate.image_similarity is not None
            else candidate.title_similarity
        )
        return (primary, candidate.title_similarity)

    @staticmethod
    def _classify(confidence: float, auto_threshold: float, review_threshold: float) -> MatchStatus:
        """Map a confidence score to a :class:`MatchStatus`."""
        if confidence >= auto_threshold:
            return MatchStatus.AUTO
        if confidence >= review_threshold:
            return MatchStatus.REVIEW
        return MatchStatus.REJECT


def _parse_verifier_response(raw: str) -> tuple[float, str]:
    """
    Parse a ``'<score>|<reason>'`` verifier response into ``(confidence, reason)``.

    Falls back to ``(0.0, raw)`` when the score cannot be parsed, and clamps the
    confidence into ``[0.0, 1.0]``.
    """
    text = raw.strip()
    score_part, _, reason_part = text.partition("|")
    try:
        confidence = float(score_part.strip())
    except (ValueError, TypeError):
        return 0.0, text
    confidence = max(0.0, min(1.0, confidence))
    reason = reason_part.strip() or text
    return confidence, reason
