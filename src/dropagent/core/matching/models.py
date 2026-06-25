"""
Data models for the product matching engine.

These dataclasses describe the inputs and outputs of the demand-first
matching flow that links a trending Naver product to the same item on
AliExpress.  They are intentionally framework-light (plain dataclasses /
``StrEnum``) so they can be constructed cheaply in tests and serialized
without pulling in heavyweight dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


@dataclass
class NaverProductRef:
    """
    Reference to a trending Naver product to be matched on AliExpress.

    Attributes:
        title_ko: Korean product title as listed on Naver.
        price: Naver listing price in KRW (integer won).
        image_url: Optional product thumbnail URL (used by image-based verifiers).
        category: Optional Naver category name, useful for translation context.
    """

    title_ko: str
    price: int
    image_url: str = ""
    category: str = ""


@dataclass
class MatchCandidate:
    """
    A single AliExpress product evaluated as a possible match.

    Attributes:
        ali_product: The underlying AliExpress product (``AliProduct``-like object).
        title_similarity: Token-overlap similarity between query and product title (0..1).
        price_ratio: AliExpress price converted to KRW divided by the Naver price.
        image_similarity: Perceptual-hash photo similarity to the Naver product
            (0..1), or ``None`` when no image scorer ran / images were missing.
        confidence: Verifier confidence that this is the same item (0..1).
        reason: Human-readable explanation produced by the verifier.
    """

    ali_product: Any
    title_similarity: float
    price_ratio: float
    image_similarity: float | None = None
    confidence: float = 0.0
    reason: str = ""


class MatchStatus(StrEnum):
    """Outcome classification for a match attempt."""

    AUTO = "auto"
    REVIEW = "review"
    REJECT = "reject"


@dataclass
class MatchResult:
    """
    Result of matching a Naver product against AliExpress search results.

    Attributes:
        status: Final decision (auto-accept / human-review / reject).
        query_en: English search query used against AliExpress.
        best: The highest-confidence candidate, or ``None`` if nothing was plausible.
        candidates: All shortlisted candidates that were verified.
    """

    status: MatchStatus
    query_en: str
    best: MatchCandidate | None
    candidates: list[MatchCandidate] = field(default_factory=list)
