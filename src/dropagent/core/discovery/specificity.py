"""
Keyword specificity / commercial-intent filters for demand-first discovery.

Narrows broad head terms (대표키워드) down to sourceable long-tail (세부키워드),
per ``docs/RESEARCH_discovery.md`` §2.3 (쇼핑성 vs 정보성) and the seller-tool
대표->세부 consensus (ItemScout / PandaRank / ...). The Search Ad keyword tool
already returns 연관키워드 (long-tail children of a seed), so this is a *filter*
on the expansion, not a new data source.

Pure functions, no I/O -- unit-testable without credentials.

NOTE (known limitation): Korean compound nouns without spaces (e.g.
'차량용거치대') are not morphologically split; ``is_specific`` falls back to a
character-length heuristic for single-token keywords. A morphological analyzer
could improve this but is intentionally avoided to keep deps light.
"""

from __future__ import annotations

from collections.abc import Iterable

# A keyword counts as "specific" if it has >= this many whitespace tokens ...
SPECIFIC_MIN_TOKENS = 2
# ... OR (for space-less Korean compounds like '골전도이어폰') its de-spaced
# length is at least this many characters.
SPECIFIC_MIN_CHARS = 6

# Broad, non-sourceable brand / IP terms to drop (price-war + 상표 risk).
# Lowercased; matched as a substring of the de-spaced keyword. Conservative and
# meant to be extended/overridden by the caller.
DEFAULT_BRAND_STOPWORDS: frozenset[str] = frozenset(
    {
        "삼성", "갤럭시", "애플", "아이폰", "에어팟", "apple", "lg", "소니", "sony",
        "샤오미", "xiaomi", "다이슨", "dyson", "나이키", "nike", "아디다스", "adidas",
        "구찌", "샤넬", "루이비통", "프라다", "발뮤다",
    }
)


def normalize(keyword: str) -> str:
    """De-space + lowercase a keyword for stable comparison."""
    return keyword.replace(" ", "").strip().lower()


def is_head_term(keyword: str, seeds: Iterable[str]) -> bool:
    """True if the keyword is (effectively) one of the seed head terms."""
    norm = normalize(keyword)
    return bool(norm) and norm in {normalize(s) for s in seeds}


def is_specific(
    keyword: str,
    seeds: Iterable[str] = (),
    *,
    min_tokens: int = SPECIFIC_MIN_TOKENS,
    min_chars: int = SPECIFIC_MIN_CHARS,
) -> bool:
    """
    Decide whether a keyword is a specific long-tail term (keep) vs a broad
    head term (drop).

    Drops exact seed head terms; otherwise keeps a keyword that either has
    ``>= min_tokens`` whitespace tokens (e.g. '골전도 러닝 이어폰') or whose
    de-spaced length is ``>= min_chars`` (space-less compounds like
    '골전도이어폰'). Bare head terms like '이어폰' / '무선이어폰' fall through
    and are dropped.
    """
    if is_head_term(keyword, seeds):
        return False
    if len(keyword.split()) >= min_tokens:
        return True
    return len(normalize(keyword)) >= min_chars


def is_branded(keyword: str, brands: Iterable[str] = DEFAULT_BRAND_STOPWORDS) -> bool:
    """True if the keyword contains a brand / IP stopword (substring, de-spaced)."""
    norm = normalize(keyword)
    return any(normalize(b) in norm for b in brands if b)
