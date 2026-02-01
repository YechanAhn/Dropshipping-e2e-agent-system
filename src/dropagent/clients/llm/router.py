"""
LLM 모델 라우터 모듈

태스크 유형에 따라 적절한 Claude 모델로 요청을 라우팅합니다.
PRD v2에 정의된 태스크별 모델 매핑을 따릅니다:
  - 고품질 태스크 (번역, 설명, CS 응답, 이미지 분석) → Claude Sonnet 4
  - 경량 태스크 (카테고리 매칭, 키워드 추출, CS 분류) → Claude Haiku 3.5
"""

import asyncio
import json
from typing import Any

from anthropic import (
    APIConnectionError,
    APITimeoutError,
    AsyncAnthropic,
)
from anthropic import (
    RateLimitError as AnthropicRateLimitError,
)

from dropagent.config import get_settings
from dropagent.utils.exceptions import APIError, RateLimitError
from dropagent.utils.logging import get_logger

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

logger = get_logger(__name__)


class LLMRouter:
    """
    태스크별 Claude 모델 라우터.

    태스크 유형에 따라 적합한 모델을 선택하고, 캐시 확인 후
    Anthropic Messages API를 호출합니다. 실패 시 지수 백오프 재시도를 수행합니다.

    Args:
        settings: 애플리케이션 설정. None이면 get_settings()로 로드합니다.
        cache: LLM 응답 캐시. None이면 기본값으로 새로 생성합니다.

    Examples:
        >>> router = LLMRouter()
        >>> name_ko = await router.translate_product_name(
        ...     "Wireless Bluetooth Earbuds TWS",
        ...     "Electronics > Headphones",
        ... )
    """

    # PRD v2 태스크별 모델 라우팅 테이블
    TASK_MODELS: dict[str, str] = {
        "translation": "claude-sonnet-4-20250514",
        "description": "claude-sonnet-4-20250514",
        "category_match": "claude-3-5-haiku-20241022",
        "keyword_extract": "claude-3-5-haiku-20241022",
        "cs_response": "claude-sonnet-4-20250514",
        "cs_classify": "claude-3-5-haiku-20241022",
        "image_analysis": "claude-sonnet-4-20250514",
    }

    # 태스크별 max_tokens 기본값
    TASK_MAX_TOKENS: dict[str, int] = {
        "translation": 256,
        "description": 4096,
        "category_match": 256,
        "keyword_extract": 512,
        "cs_response": 1024,
        "cs_classify": 256,
        "image_analysis": 2048,
    }

    # 재시도 설정
    MAX_RETRIES = 3
    BASE_RETRY_DELAY = 1.0  # seconds

    def __init__(
        self,
        settings: Any | None = None,
        cache: LLMCache | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self.client = AsyncAnthropic(api_key=self._settings.anthropic.api_key)
        self.cache = cache or LLMCache()

        logger.info(
            "llm_router_initialized",
            task_count=len(self.TASK_MODELS),
            cache_max_size=self.cache._max_size,
        )

    # ------------------------------------------------------------------
    # Core routing method
    # ------------------------------------------------------------------

    async def route(
        self,
        task_type: str,
        prompt: str,
        *,
        use_cache: bool = True,
        max_tokens: int | None = None,
        temperature: float = 0.3,
    ) -> str:
        """
        태스크를 적절한 모델로 라우팅하고 응답을 반환합니다.

        1. 캐시 확인 (use_cache=True 인 경우)
        2. 모델 선택
        3. API 호출 (실패 시 지수 백오프 재시도)
        4. 결과 캐싱

        Args:
            task_type: 태스크 유형 (TASK_MODELS 키).
            prompt: 완성된 프롬프트 문자열.
            use_cache: 캐시 사용 여부.
            max_tokens: 최대 생성 토큰 수. None이면 태스크 기본값.
            temperature: 생성 온도 (0.0~1.0).

        Returns:
            LLM 응답 텍스트.

        Raises:
            APIError: 모든 재시도 실패 시.
            RateLimitError: Rate limit 초과로 재시도 불가 시.
            ValueError: 알 수 없는 task_type.
        """
        if task_type not in self.TASK_MODELS:
            raise ValueError(
                f"Unknown task_type: {task_type!r}. "
                f"Available: {list(self.TASK_MODELS.keys())}"
            )

        model = self.TASK_MODELS[task_type]
        resolved_max_tokens = max_tokens or self.TASK_MAX_TOKENS.get(task_type, 1024)

        # 1. Cache lookup
        if use_cache:
            cached = self.cache.get(model, prompt)
            if cached is not None:
                logger.info(
                    "llm_cache_hit",
                    task_type=task_type,
                    model=model,
                )
                return cached

        # 2. API call with retry
        response_text = await self._call_with_retry(
            model=model,
            prompt=prompt,
            max_tokens=resolved_max_tokens,
            temperature=temperature,
            task_type=task_type,
        )

        # 3. Cache result
        if use_cache:
            self.cache.set(model, prompt, response_text)

        return response_text

    # ------------------------------------------------------------------
    # API call with retry logic
    # ------------------------------------------------------------------

    async def _call_with_retry(
        self,
        model: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        task_type: str,
    ) -> str:
        """지수 백오프를 사용하여 Anthropic API를 호출합니다."""
        last_error: Exception | None = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = await self.client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=[{"role": "user", "content": prompt}],
                )

                # Extract text content
                response_text = ""
                for block in response.content:
                    if block.type == "text":
                        response_text += block.text

                # Log token usage
                logger.info(
                    "llm_api_call_success",
                    task_type=task_type,
                    model=model,
                    attempt=attempt,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    stop_reason=response.stop_reason,
                )

                return response_text.strip()

            except AnthropicRateLimitError as exc:
                last_error = exc
                retry_after = _extract_retry_after(exc)
                delay = retry_after or (self.BASE_RETRY_DELAY * (2 ** (attempt - 1)))

                logger.warning(
                    "llm_rate_limit_hit",
                    task_type=task_type,
                    model=model,
                    attempt=attempt,
                    retry_after=delay,
                )

                if attempt < self.MAX_RETRIES:
                    await asyncio.sleep(delay)
                else:
                    raise RateLimitError(
                        message=f"Rate limit exceeded after {self.MAX_RETRIES} retries",
                        api_name="anthropic",
                        retry_after=int(delay),
                        original_error=exc,
                    ) from exc

            except APITimeoutError as exc:
                last_error = exc
                delay = self.BASE_RETRY_DELAY * (2 ** (attempt - 1))

                logger.warning(
                    "llm_api_timeout",
                    task_type=task_type,
                    model=model,
                    attempt=attempt,
                    delay=delay,
                )

                if attempt < self.MAX_RETRIES:
                    await asyncio.sleep(delay)
                else:
                    raise APIError(
                        message=f"Anthropic API timeout after {self.MAX_RETRIES} retries",
                        api_name="anthropic",
                        original_error=exc,
                    ) from exc

            except APIConnectionError as exc:
                last_error = exc
                delay = self.BASE_RETRY_DELAY * (2 ** (attempt - 1))

                logger.warning(
                    "llm_api_connection_error",
                    task_type=task_type,
                    model=model,
                    attempt=attempt,
                    delay=delay,
                    error=str(exc),
                )

                if attempt < self.MAX_RETRIES:
                    await asyncio.sleep(delay)
                else:
                    raise APIError(
                        message=f"Anthropic API connection error after {self.MAX_RETRIES} retries",
                        api_name="anthropic",
                        original_error=exc,
                    ) from exc

            except Exception as exc:
                logger.error(
                    "llm_api_unexpected_error",
                    task_type=task_type,
                    model=model,
                    attempt=attempt,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                raise APIError(
                    message=f"Unexpected Anthropic API error: {exc}",
                    api_name="anthropic",
                    original_error=exc,
                ) from exc

        # Should not reach here, but just in case
        raise APIError(
            message=f"All {self.MAX_RETRIES} retry attempts failed",
            api_name="anthropic",
            original_error=last_error,
        )

    # ------------------------------------------------------------------
    # High-level task methods
    # ------------------------------------------------------------------

    async def translate_product_name(
        self,
        product_name_en: str,
        category: str,
    ) -> str:
        """
        알리익스프레스 영문 상품명을 한국어로 번역합니다.

        네이버 스마트스토어 SEO에 최적화된 한국어 상품명을 반환합니다.

        Args:
            product_name_en: 영문 상품명.
            category: 상품 카테고리.

        Returns:
            번역된 한국어 상품명.
        """
        prompt = format_prompt(
            PRODUCT_TRANSLATION_PROMPT,
            product_name_en=product_name_en,
            category=category,
        )
        return await self.route("translation", prompt)

    async def generate_description(self, product_info: dict) -> str:
        """
        상품 상세설명을 생성합니다.

        Args:
            product_info: 상품 정보 딕셔너리.
                필수 키: product_name_en, product_name_ko, category,
                         price_krw, attributes, original_description

        Returns:
            HTML 형식의 한국어 상품 상세설명.
        """
        prompt = format_prompt(
            PRODUCT_DESCRIPTION_PROMPT,
            product_name_en=product_info.get("product_name_en", ""),
            product_name_ko=product_info.get("product_name_ko", ""),
            category=product_info.get("category", ""),
            price_krw=product_info.get("price_krw", ""),
            attributes=product_info.get("attributes", ""),
            original_description=product_info.get("original_description", ""),
        )
        return await self.route("description", prompt)

    async def match_category(
        self,
        ali_category: str,
        product_name: str,
    ) -> str:
        """
        알리익스프레스 카테고리를 네이버 스마트스토어 카테고리로 매칭합니다.

        Args:
            ali_category: 알리익스프레스 원본 카테고리.
            product_name: 상품명 (매칭 정확도 향상 용).

        Returns:
            JSON 문자열: {"category_id": ..., "category_name": ..., "confidence": ...}
        """
        prompt = format_prompt(
            CATEGORY_MATCHING_PROMPT,
            ali_category=ali_category,
            product_name=product_name,
        )
        return await self.route("category_match", prompt)

    async def extract_keywords(
        self,
        product_name: str,
        category: str,
    ) -> list[str]:
        """
        상품 정보에서 네이버 쇼핑 검색 태그 키워드를 추출합니다.

        Args:
            product_name: 한국어 상품명.
            category: 네이버 카테고리.

        Returns:
            키워드 문자열 리스트 (최대 10개).
        """
        prompt = format_prompt(
            KEYWORD_EXTRACTION_PROMPT,
            product_name=product_name,
            category=category,
        )
        raw = await self.route("keyword_extract", prompt)

        # Parse JSON array response
        try:
            keywords = json.loads(raw)
            if isinstance(keywords, list):
                return [str(kw).strip() for kw in keywords[:10] if kw]
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "llm_keyword_parse_failed",
                raw_response=raw[:200],
            )

        # Fallback: split by common delimiters
        return [kw.strip().strip('"').strip("'") for kw in raw.split(",") if kw.strip()][:10]

    async def classify_cs_inquiry(self, inquiry_text: str) -> str:
        """
        고객 문의를 유형별로 분류합니다.

        Args:
            inquiry_text: 고객 문의 원문.

        Returns:
            JSON 문자열: {"type": ..., "confidence": ..., "summary": ...}
        """
        prompt = format_prompt(
            CS_CLASSIFICATION_PROMPT,
            inquiry_text=inquiry_text,
        )
        return await self.route("cs_classify", prompt)

    async def generate_cs_response(
        self,
        inquiry_text: str,
        inquiry_type: str,
        product_info: dict,
    ) -> str:
        """
        고객 문의에 대한 응답 초안을 생성합니다.

        Args:
            inquiry_text: 고객 문의 원문.
            inquiry_type: 문의 유형 (classify_cs_inquiry 결과).
            product_info: 관련 상품 정보 딕셔너리.

        Returns:
            고객 응답 초안 텍스트.
        """
        # Format product_info for the prompt
        product_info_str = json.dumps(product_info, ensure_ascii=False, indent=2) if product_info else "정보 없음"

        prompt = format_prompt(
            CS_RESPONSE_PROMPT,
            inquiry_text=inquiry_text,
            inquiry_type=inquiry_type,
            product_info=product_info_str,
        )
        return await self.route("cs_response", prompt, use_cache=False)


def _extract_retry_after(exc: AnthropicRateLimitError) -> float | None:
    """Rate limit 응답에서 retry-after 값을 추출합니다."""
    try:
        if hasattr(exc, "response") and exc.response is not None:
            retry_header = exc.response.headers.get("retry-after")
            if retry_header is not None:
                return float(retry_header)
    except (ValueError, AttributeError):
        pass
    return None
