"""
LLM 클라이언트 패키지

태스크별 모델 라우팅, 응답 캐싱, 프롬프트 관리를 제공합니다.
"""

from .cache import LLMCache
from .prompts import (
    CATEGORY_MATCHING_PROMPT,
    CS_CLASSIFICATION_PROMPT,
    CS_RESPONSE_PROMPT,
    KEYWORD_EXTRACTION_PROMPT,
    PRODUCT_DESCRIPTION_PROMPT,
    PRODUCT_TRANSLATION_PROMPT,
    format_prompt,
)
from .router import LLMRouter

__all__ = [
    # Router
    "LLMRouter",
    # Cache
    "LLMCache",
    # Prompts
    "PRODUCT_TRANSLATION_PROMPT",
    "PRODUCT_DESCRIPTION_PROMPT",
    "CATEGORY_MATCHING_PROMPT",
    "KEYWORD_EXTRACTION_PROMPT",
    "CS_RESPONSE_PROMPT",
    "CS_CLASSIFICATION_PROMPT",
    "format_prompt",
]
