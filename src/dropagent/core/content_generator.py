"""
LLM 기반 상세페이지 콘텐츠 생성 모듈 (텍스트 우선 전략)

알리익스프레스 상품을 네이버 스마트스토어 등록용 리스팅으로 변환합니다.
이미지 제작/편집 대신, LLM으로 다음을 생성하는 "텍스트 우선" 전략을 사용합니다:

    1. 상품명 번역 + 네이버 SEO 최적화 (한국어)
    2. 네이버 가이드라인 기반 상세설명 (HTML)
    3. 검색 태그 키워드 추출
    4. 네이버 카테고리 매핑

핵심 컴포넌트:
    - GeneratedContent: 생성 결과 데이터클래스
    - ContentGenerator: 생성 오케스트레이터 (LLMRouter / CategoryMapper 주입 가능)

가드레일:
    - 상품명 길이 제한 (네이버 ~100자)
    - 위험/상표성 단어를 제거하고 warnings에 기록
    - 키워드 중복 제거

주의:
    build_register_payload()가 만드는 payload 스키마는 실제 네이버 커머스 API
    (register_product) 스펙에 맞춰 검증되어야 합니다. 여기서는 합리적인 구조의
    초안을 제공하며, 라이브 API 연동 시 필드명을 반드시 확인해야 합니다.
"""

from dataclasses import dataclass, field
from typing import Any

from dropagent.utils.logging import get_logger

logger = get_logger(__name__)

# 네이버 스마트스토어 상품명 최대 길이 (가이드라인 기준 약 100자)
MAX_TITLE_LENGTH = 100

# 등록 가능 태그(sellerTags) 최대 개수
MAX_SELLER_TAGS = 10

# 상표/위험성 단어 — 발견 시 상품명/키워드에서 제거하고 warnings에 기록합니다.
# (실제 운영에서는 외부 금칙어/상표 DB로 확장해야 합니다.)
AVOID_WORDS: tuple[str, ...] = (
    "nike",
    "adidas",
    "gucci",
    "chanel",
    "louis vuitton",
    "supreme",
    "apple",
    "samsung",
    "rolex",
    "disney",
    "정품",
    "명품",
    "최저가",
    "1위",
    "100%",
)


@dataclass
class GeneratedContent:
    """LLM으로 생성된 네이버 등록용 상세페이지 콘텐츠."""

    title_ko: str
    description_html: str
    keywords: list[str]
    naver_category_id: str | None
    naver_category_name: str | None
    source_image_urls: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _get_attr(obj: Any, key: str, default: Any = None) -> Any:
    """객체 속성(getattr) 또는 dict 키(get)에서 값을 안전하게 추출합니다.

    AliProduct/AliProductDetail (pydantic) 와 plain dict 입력을 모두 지원합니다.
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _extract_sale_price(ali_product: Any) -> Any:
    """상품에서 sale_price를 추출합니다 (price.sale_price 또는 평면 키)."""
    price = _get_attr(ali_product, "price")
    if price is not None:
        sale = _get_attr(price, "sale_price")
        if sale is not None:
            return sale
    # 평면 dict 입력에 대한 폴백
    return _get_attr(ali_product, "sale_price")


def _strip_avoid_words(text: str) -> tuple[str, list[str]]:
    """상표/위험성 단어를 텍스트에서 제거하고, 제거된 단어 목록을 반환합니다.

    Returns:
        (정제된 텍스트, 발견된 위험 단어 리스트)
    """
    if not text:
        return text, []

    found: list[str] = []
    cleaned = text
    lowered = cleaned.lower()
    for word in AVOID_WORDS:
        if word.lower() in lowered:
            found.append(word)
            # 대소문자 무관하게 제거
            idx = lowered.find(word.lower())
            while idx != -1:
                cleaned = cleaned[:idx] + cleaned[idx + len(word):]
                lowered = cleaned.lower()
                idx = lowered.find(word.lower())

    # 단어 제거 후 남은 다중 공백 정리
    cleaned = " ".join(cleaned.split())
    return cleaned, found


def _dedupe_keywords(keywords: list[str]) -> list[str]:
    """키워드 리스트에서 중복(대소문자/공백 무시)을 제거하고 순서를 유지합니다."""
    seen: set[str] = set()
    result: list[str] = []
    for kw in keywords:
        if not kw:
            continue
        normalized = kw.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


class ContentGenerator:
    """알리익스프레스 상품 → 네이버 등록 콘텐츠 생성기.

    LLMRouter와 CategoryMapper를 주입받아 상세페이지 텍스트 콘텐츠를 생성합니다.
    의존성은 모두 선택적으로 주입 가능하며, 주입되지 않은 경우 메서드 실행 시점에
    지연(lazy) 생성됩니다. 따라서 생성자만으로는 API 키가 필요하지 않습니다.

    Args:
        llm_router: LLMRouter 인스턴스 (테스트 시 페이크 라우터 주입).
        category_mapper: CategoryMapper 인스턴스.

    Examples:
        >>> generator = ContentGenerator(llm_router=fake_router, category_mapper=mapper)
        >>> content = await generator.generate(ali_product, target_keyword="링라이트")
    """

    def __init__(
        self,
        llm_router: Any | None = None,
        category_mapper: Any | None = None,
    ) -> None:
        self._llm_router = llm_router
        self._category_mapper = category_mapper

        logger.info(
            "content_generator_initialized",
            llm_router_injected=llm_router is not None,
            category_mapper_injected=category_mapper is not None,
        )

    # ------------------------------------------------------------------
    # 지연 의존성 생성 (생성자에서 API 키 없이도 구성 가능하도록)
    # ------------------------------------------------------------------

    @property
    def llm_router(self) -> Any:
        """주입된 LLMRouter를 반환하거나 지연 생성합니다."""
        if self._llm_router is None:
            from dropagent.clients.llm.router import LLMRouter

            self._llm_router = LLMRouter()
        return self._llm_router

    @property
    def category_mapper(self) -> Any:
        """주입된 CategoryMapper를 반환하거나 지연 생성합니다."""
        if self._category_mapper is None:
            from dropagent.core.category_mapper import CategoryMapper

            self._category_mapper = CategoryMapper()
        return self._category_mapper

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    async def generate(
        self,
        ali_product: Any,
        *,
        target_keyword: str | None = None,
    ) -> GeneratedContent:
        """알리익스프레스 상품에서 네이버 등록용 콘텐츠를 생성합니다.

        다음 단계를 수행합니다:
            1. 상품명 번역 + SEO (한국어)
            2. 네이버 카테고리 매핑
            3. 상세설명 생성 (HTML)
            4. 검색 키워드 추출

        Args:
            ali_product: AliProduct / AliProductDetail 인스턴스 또는 평면 dict.
            target_keyword: 강조할 타깃 키워드 (선택). 키워드 목록 상단에 추가됩니다.

        Returns:
            GeneratedContent: 생성된 콘텐츠 + 가드레일 warnings.
        """
        warnings: list[str] = []

        title_en = str(_get_attr(ali_product, "title", "") or "")
        ali_category = str(_get_attr(ali_product, "category_name", "") or "")
        description_src = str(_get_attr(ali_product, "description", "") or "")

        # 1) 카테고리 매핑 (LLM 호출 전에 매핑해두면 후속 단계에 카테고리명 활용 가능)
        naver_category = self.category_mapper.map_category(ali_category)
        naver_category_id = _get_attr(naver_category, "id")
        naver_category_name = _get_attr(naver_category, "name")

        # 2) 상품명 번역 + SEO
        title_ko_raw = await self.llm_router.translate_product_name(
            title_en,
            ali_category,
        )
        title_ko, title_avoid = _strip_avoid_words(str(title_ko_raw or "").strip())
        if title_avoid:
            warnings.append(
                f"상품명에서 상표/위험 단어 제거: {', '.join(title_avoid)}"
            )

        # 길이 제한 (네이버 ~100자)
        if len(title_ko) > MAX_TITLE_LENGTH:
            warnings.append(
                f"상품명이 {MAX_TITLE_LENGTH}자를 초과하여 잘렸습니다 "
                f"(원본 {len(title_ko)}자)."
            )
            title_ko = title_ko[:MAX_TITLE_LENGTH].rstrip()

        # 3) 상세설명 생성
        price_krw = _extract_sale_price(ali_product)
        product_info: dict[str, Any] = {
            "product_name_en": title_en,
            "product_name_ko": title_ko,
            "category": naver_category_name or ali_category,
            "price_krw": str(price_krw) if price_krw is not None else "",
            "attributes": self._summarize_attributes(ali_product),
            "original_description": description_src,
        }
        description_html = await self.llm_router.generate_description(product_info)
        description_html = str(description_html or "")

        # 4) 키워드 추출
        raw_keywords = await self.llm_router.extract_keywords(
            title_ko,
            naver_category_name or ali_category,
        )
        keywords = list(raw_keywords or [])

        # 타깃 키워드를 최상단에 추가
        if target_keyword:
            keywords.insert(0, target_keyword)

        keywords = _dedupe_keywords(keywords)

        # 키워드 가드레일: 위험 단어가 그대로 들어간 키워드 제거
        safe_keywords: list[str] = []
        for kw in keywords:
            _, kw_avoid = _strip_avoid_words(kw)
            if kw_avoid:
                warnings.append(
                    f"키워드에서 상표/위험 단어 제외: {kw}"
                )
                continue
            safe_keywords.append(kw)
        keywords = safe_keywords

        # 이미지 URL 수집 (텍스트 우선 전략이지만 원본 이미지는 그대로 활용)
        source_image_urls = self._collect_image_urls(ali_product)

        logger.info(
            "content_generated",
            product_id=_get_attr(ali_product, "product_id"),
            title_len=len(title_ko),
            keyword_count=len(keywords),
            naver_category_id=naver_category_id,
            warning_count=len(warnings),
        )

        return GeneratedContent(
            title_ko=title_ko,
            description_html=description_html,
            keywords=keywords,
            naver_category_id=naver_category_id,
            naver_category_name=naver_category_name,
            source_image_urls=source_image_urls,
            warnings=warnings,
        )

    def build_register_payload(
        self,
        content: GeneratedContent,
        price: int,
        *,
        stock: int = 999,
        **extra: Any,
    ) -> dict[str, Any]:
        """네이버 커머스 register_product용 payload 초안을 조립합니다.

        주의:
            이 payload 스키마는 실제 네이버 커머스 API 스펙에 맞춰 반드시 검증되어야
            합니다. 여기서는 originProduct 중심의 합리적인 구조를 제공하며, 필드명/구조는
            라이브 API 문서를 기준으로 확정해야 합니다.

        Args:
            content: generate()가 반환한 GeneratedContent.
            price: 판매가 (원, 정수).
            stock: 재고 수량 (기본 999).
            **extra: originProduct에 병합할 추가 필드.

        Returns:
            register_product 요청 payload dict.
        """
        # sellerTags는 키워드를 기반으로 구성 (최대 개수 제한)
        seller_tags = [
            {"text": kw} for kw in content.keywords[:MAX_SELLER_TAGS]
        ]

        # 대표 이미지 + 추가 이미지 분리
        images = list(content.source_image_urls)
        representative_image = images[0] if images else None
        optional_images = images[1:] if len(images) > 1 else []

        origin_product: dict[str, Any] = {
            "name": content.title_ko,
            "salePrice": int(price),
            "stockQuantity": int(stock),
            "leafCategoryId": content.naver_category_id,
            "detailContent": content.description_html,
            "images": {
                "representativeImage": (
                    {"url": representative_image} if representative_image else None
                ),
                "optionalImages": [{"url": url} for url in optional_images],
            },
            "sellerTags": seller_tags,
        }

        # 호출자가 제공한 추가 필드 병합 (originProduct 레벨)
        origin_product.update(extra)

        payload: dict[str, Any] = {
            "originProduct": origin_product,
        }

        logger.info(
            "register_payload_built",
            sale_price=int(price),
            stock=int(stock),
            leaf_category_id=content.naver_category_id,
            tag_count=len(seller_tags),
            image_count=len(images),
        )

        return payload

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    @staticmethod
    def _summarize_attributes(ali_product: Any) -> str:
        """상품 옵션/평점/주문수를 LLM 프롬프트용 속성 요약 문자열로 변환합니다."""
        parts: list[str] = []

        rating = _get_attr(ali_product, "rating")
        if rating:
            parts.append(f"평점: {rating}")

        order_count = _get_attr(ali_product, "order_count")
        if order_count:
            parts.append(f"주문수: {order_count}")

        reviews_count = _get_attr(ali_product, "reviews_count")
        if reviews_count:
            parts.append(f"리뷰수: {reviews_count}")

        options = _get_attr(ali_product, "options")
        if options:
            option_values: list[str] = []
            for opt in options:
                value = _get_attr(opt, "value") or _get_attr(opt, "name")
                if value:
                    option_values.append(str(value))
            if option_values:
                # 너무 길어지지 않도록 상위 10개만
                preview = ", ".join(option_values[:10])
                parts.append(f"옵션: {preview}")

        return " / ".join(parts)

    @staticmethod
    def _collect_image_urls(ali_product: Any) -> list[str]:
        """상품 대표 이미지 + 옵션 이미지 URL을 중복 없이 수집합니다."""
        urls: list[str] = []

        main_image = _get_attr(ali_product, "image_url")
        if main_image:
            urls.append(str(main_image))

        options = _get_attr(ali_product, "options")
        if options:
            for opt in options:
                opt_img = _get_attr(opt, "image_url")
                if opt_img:
                    urls.append(str(opt_img))

        # 순서를 유지하며 중복 제거
        seen: set[str] = set()
        result: list[str] = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                result.append(url)
        return result
