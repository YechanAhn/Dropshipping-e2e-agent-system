"""
Product matching engine package.

Links a trending Naver product to the same item on AliExpress via a
translate -> search -> filter -> verify -> threshold pipeline.

Public API:
    - :class:`NaverProductRef`, :class:`MatchCandidate`, :class:`MatchResult`,
      :class:`MatchStatus` (models)
    - :class:`ProductMatcher` and the :func:`title_similarity` /
      :func:`extract_spec_tokens` helpers (matcher)
    - :data:`Translator` / :data:`Verifier` / :data:`ImageScorer` type aliases
      for injected dependencies
"""

from dropagent.core.matching.matcher import (
    ImageScorer,
    ProductMatcher,
    Translator,
    Verifier,
    extract_spec_tokens,
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
    "ImageScorer",
    "title_similarity",
    "extract_spec_tokens",
]
