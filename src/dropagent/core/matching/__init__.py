"""
Product matching engine package.

Links a trending Naver product to the same item on AliExpress via a
translate -> search -> filter -> verify -> threshold pipeline.

Public API:
    - :class:`NaverProductRef`, :class:`MatchCandidate`, :class:`MatchResult`,
      :class:`MatchStatus` (models)
    - :class:`ProductMatcher` and the :func:`title_similarity` helper (matcher)
    - :data:`Translator` / :data:`Verifier` type aliases for injected dependencies
"""

from dropagent.core.matching.matcher import (
    ProductMatcher,
    Translator,
    Verifier,
    title_similarity,
)
from dropagent.core.matching.models import (
    MatchCandidate,
    MatchResult,
    MatchStatus,
    NaverProductRef,
)

__all__ = [
    "NaverProductRef",
    "MatchCandidate",
    "MatchResult",
    "MatchStatus",
    "ProductMatcher",
    "Translator",
    "Verifier",
    "title_similarity",
]
