"""
Tests for ContentGenerator (LLM 기반 상세페이지 콘텐츠 생성).

페이크 LLM 라우터를 사용하여 네트워크 없이 검증합니다. 커버리지:
    - generate() 가 title_ko / description_html / keywords 를 채우고 카테고리를 매핑
    - AliProduct 유사 객체와 평면 dict 입력 모두 처리
    - 상품명 길이 제한, 키워드 중복 제거
    - build_register_payload() 가 기대한 중첩 키와 주어진 가격을 포함
    - 상표/위험 단어 가드레일이 warnings 를 기록
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from dropagent.core.category_mapper import CategoryMapper
from dropagent.core.content_generator import (
    ContentGenerator,
    GeneratedContent,
)

# =====================================================================
# Fake LLM router
# =====================================================================


# 11-섹션(data-sec) 키 — DETAIL_PAGE_PROMPT 구조와 동일해야 한다.
DETAIL_SECTIONS: tuple[str, ...] = (
    "hook",
    "problem",
    "benefit",
    "detail_spec",
    "usage",
    "size_option",
    "trust",
    "shipping",
    "cert_as",
    "faq",
    "cta_review",
)


def _canned_detail_html(*, with_markers: bool = True, with_avoid: bool = False) -> str:
    """11개 <section data-sec="..."> 를 담은 결정적 상세페이지 HTML 픽스처."""
    sections: list[str] = []
    for sec in DETAIL_SECTIONS:
        body = f"<h2>{sec} 소제목</h2><p>{sec} 본문입니다.</p>"
        if sec == "usage" and with_markers:
            body += "<!-- VIDEO_SLOT -->"
        if sec == "detail_spec" and with_markers:
            body += '<img src="https://img.example.com/main.jpg"><!-- NEEDS_IMAGE_CLEANUP -->'
        if sec == "cta_review" and with_avoid:
            body += "<p>지금이 최저가 정품 1위 상품이에요.</p>"
        sections.append(f'<section data-sec="{sec}">{body}</section>')
    return "".join(sections)


class FakeLLMRouter:
    """LLMRouter의 공개 async 메서드 시그니처를 흉내내는 페이크.

    호출 인자를 기록하고, 결정적(deterministic)인 결과를 반환합니다.
    keywords 응답에 의도적으로 중복을 넣어 중복 제거를 검증합니다.
    """

    def __init__(
        self,
        *,
        translated_name: str = "무선 블루투스 이어폰 TWS 노이즈캔슬링",
        keywords: list[str] | None = None,
        description: str = "<div><h2>상품 상세</h2><p>고품질 무선 이어폰입니다.</p></div>",
        detail_html: str | None = None,
    ) -> None:
        self.translated_name = translated_name
        self.keywords = keywords if keywords is not None else [
            "이어폰",
            "블루투스",
            "이어폰",  # 중복 (dedupe 대상)
            "무선이어폰",
            "TWS",
        ]
        self.description = description
        self.detail_html = detail_html if detail_html is not None else _canned_detail_html()
        self.calls: dict[str, list[tuple]] = {
            "translate": [],
            "describe": [],
            "detail": [],
            "keywords": [],
        }

    async def translate_product_name(self, product_name_en: str, category: str) -> str:
        self.calls["translate"].append((product_name_en, category))
        return self.translated_name

    async def generate_description(self, product_info: dict) -> str:
        self.calls["describe"].append((product_info,))
        return self.description

    async def generate_detail_page(self, product_info: dict) -> str:
        self.calls["detail"].append((product_info,))
        return self.detail_html

    async def extract_keywords(self, product_name: str, category: str) -> list[str]:
        self.calls["keywords"].append((product_name, category))
        return list(self.keywords)

    async def match_category(self, ali_category: str, product_name: str) -> str:
        return '{"category_id": "0", "category_name": "기타", "confidence": 0.1}'


# =====================================================================
# Sample inputs
# =====================================================================


def _make_ali_object():
    """AliProduct 유사 객체 (getattr 접근). price.sale_price 중첩 포함."""
    price = SimpleNamespace(original_price=Decimal("12.00"), sale_price=Decimal("8.50"))
    option = SimpleNamespace(
        sku_id="sku1",
        name="Color",
        value="Black",
        image_url="https://img.example.com/opt-black.jpg",
        price=None,
        stock=50,
    )
    return SimpleNamespace(
        product_id="ALI-555",
        title="Wireless Bluetooth Earbuds TWS Noise Cancelling",
        price=price,
        category_name="Consumer Electronics",
        image_url="https://img.example.com/main.jpg",
        rating=Decimal("4.7"),
        order_count=1500,
        reviews_count=320,
        description="<p>Original AliExpress description.</p>",
        options=[option],
    )


def _make_ali_dict():
    """평면 dict 입력 (get 접근). price 가 중첩 dict."""
    return {
        "product_id": "ALI-777",
        "title": "LED Ring Light with Tripod Stand",
        "price": {"original_price": "20.00", "sale_price": "13.00"},
        "category_name": "Consumer Electronics",
        "image_url": "https://img.example.com/ring.jpg",
        "rating": 4.5,
        "order_count": 800,
        "description": "<p>Ring light desc.</p>",
        "options": [],
    }


@pytest.fixture
def fake_router():
    return FakeLLMRouter()


@pytest.fixture
def generator(fake_router):
    return ContentGenerator(llm_router=fake_router, category_mapper=CategoryMapper())


# =====================================================================
# generate() — populated fields + category mapping
# =====================================================================


class TestGenerate:
    """ContentGenerator.generate() 동작 검증."""

    async def test_returns_generated_content(self, generator):
        """결과는 GeneratedContent 인스턴스."""
        content = await generator.generate(_make_ali_object())
        assert isinstance(content, GeneratedContent)

    async def test_populates_core_fields(self, generator):
        """title_ko / description_html / keywords 가 채워진다."""
        content = await generator.generate(_make_ali_object())
        assert content.title_ko
        assert content.title_ko == "무선 블루투스 이어폰 TWS 노이즈캔슬링"
        assert content.description_html
        assert "<" in content.description_html  # HTML 형태
        assert len(content.keywords) > 0

    async def test_category_is_mapped(self, generator):
        """Consumer Electronics -> 디지털/가전 으로 매핑."""
        content = await generator.generate(_make_ali_object())
        assert content.naver_category_id == "50000100"
        assert content.naver_category_name == "디지털/가전"

    async def test_collects_source_images(self, generator):
        """대표 이미지 + 옵션 이미지를 수집."""
        content = await generator.generate(_make_ali_object())
        assert "https://img.example.com/main.jpg" in content.source_image_urls
        assert "https://img.example.com/opt-black.jpg" in content.source_image_urls

    async def test_translate_called_with_title_and_category(self, generator, fake_router):
        """라우터 translate 가 영문 상품명/카테고리로 호출."""
        await generator.generate(_make_ali_object())
        assert fake_router.calls["translate"]
        name_en, category = fake_router.calls["translate"][0]
        assert name_en == "Wireless Bluetooth Earbuds TWS Noise Cancelling"
        assert category == "Consumer Electronics"

    async def test_description_receives_price(self, generator, fake_router):
        """상세페이지 생성 시 price.sale_price 가 product_info로 전달."""
        await generator.generate(_make_ali_object())
        assert fake_router.calls["detail"]
        (product_info,) = fake_router.calls["detail"][0]
        assert product_info["price_krw"] == "8.50"
        assert product_info["product_name_ko"] == "무선 블루투스 이어폰 TWS 노이즈캔슬링"


# =====================================================================
# generate() — 11-섹션 상세페이지 HTML
# =====================================================================


class TestDetailPage:
    """generate() 가 11-섹션 상세페이지 HTML을 description_html 에 담는지 검증."""

    async def test_all_eleven_sections_present(self, generator):
        """11개 <section data-sec="..."> 키가 모두 description_html 에 존재."""
        content = await generator.generate(_make_ali_object())
        for sec in DETAIL_SECTIONS:
            assert f'data-sec="{sec}"' in content.description_html

    async def test_detail_page_called_not_legacy_description(self, generator, fake_router):
        """레거시 generate_description 이 아니라 generate_detail_page 가 호출된다."""
        await generator.generate(_make_ali_object())
        assert fake_router.calls["detail"]
        assert not fake_router.calls["describe"]

    async def test_detail_receives_image_urls_and_options(self, generator, fake_router):
        """수집한 이미지 URL과 직렬화된 옵션이 product_info 로 전달."""
        await generator.generate(_make_ali_object())
        (product_info,) = fake_router.calls["detail"][0]
        assert "https://img.example.com/main.jpg" in product_info["image_urls"]
        assert "https://img.example.com/opt-black.jpg" in product_info["image_urls"]
        # _make_ali_object 의 옵션: name=Color, value=Black
        assert "Color: Black" in product_info["options"]

    async def test_options_empty_when_absent(self, generator, fake_router):
        """옵션이 없으면 options 문자열은 빈 값."""
        await generator.generate(_make_ali_dict())  # options=[]
        (product_info,) = fake_router.calls["detail"][0]
        assert product_info["options"] == ""

    async def test_markers_preserved(self):
        """NEEDS_IMAGE_CLEANUP / VIDEO_SLOT 마커는 HTML 에 보존된다."""
        router = FakeLLMRouter(detail_html=_canned_detail_html(with_markers=True))
        gen = ContentGenerator(llm_router=router, category_mapper=CategoryMapper())
        content = await gen.generate(_make_ali_object())
        assert "<!-- NEEDS_IMAGE_CLEANUP -->" in content.description_html
        assert "<!-- VIDEO_SLOT -->" in content.description_html

    async def test_avoid_words_stripped_from_html(self):
        """상세페이지 HTML 에서 상표/위험 단어가 제거되고 마커는 유지된다."""
        router = FakeLLMRouter(
            detail_html=_canned_detail_html(with_markers=True, with_avoid=True)
        )
        gen = ContentGenerator(llm_router=router, category_mapper=CategoryMapper())
        content = await gen.generate(_make_ali_object())
        assert "최저가" not in content.description_html
        assert "정품" not in content.description_html
        assert "1위" not in content.description_html
        # 제거 사실이 warnings 에 기록
        assert any("상세페이지" in w for w in content.warnings)
        # 마커는 그대로 보존
        assert "<!-- NEEDS_IMAGE_CLEANUP -->" in content.description_html
        assert "<!-- VIDEO_SLOT -->" in content.description_html
        # 11 섹션은 그대로 유지
        for sec in DETAIL_SECTIONS:
            assert f'data-sec="{sec}"' in content.description_html


# =====================================================================
# Input flexibility: object vs dict
# =====================================================================


class TestInputTypes:
    """AliProduct 유사 객체 / 평면 dict 입력 모두 처리."""

    async def test_handles_object_input(self, generator):
        content = await generator.generate(_make_ali_object())
        assert content.naver_category_name == "디지털/가전"

    async def test_handles_dict_input(self, generator, fake_router):
        content = await generator.generate(_make_ali_dict())
        assert isinstance(content, GeneratedContent)
        assert content.naver_category_name == "디지털/가전"
        # 중첩 dict price 에서 sale_price 추출 확인
        (product_info,) = fake_router.calls["detail"][0]
        assert product_info["price_krw"] == "13.00"
        assert "https://img.example.com/ring.jpg" in content.source_image_urls


# =====================================================================
# Guardrails: keyword dedupe, title cap, target keyword
# =====================================================================


class TestGuardrails:
    """길이 제한 / 중복 제거 / 위험 단어 가드레일."""

    async def test_keywords_deduped(self, generator):
        """중복 키워드(이어폰 x2)는 한 번만 남는다."""
        content = await generator.generate(_make_ali_object())
        lowered = [k.lower() for k in content.keywords]
        assert len(lowered) == len(set(lowered))
        assert lowered.count("이어폰") == 1

    async def test_target_keyword_prepended(self, generator):
        """target_keyword 가 키워드 최상단에 추가된다."""
        content = await generator.generate(
            _make_ali_object(), target_keyword="가성비 이어폰"
        )
        assert content.keywords[0] == "가성비 이어폰"

    async def test_title_length_capped(self):
        """100자를 초과하는 상품명은 잘리고 경고가 기록된다."""
        long_name = "초" * 150
        router = FakeLLMRouter(translated_name=long_name)
        gen = ContentGenerator(llm_router=router, category_mapper=CategoryMapper())
        content = await gen.generate(_make_ali_object())
        assert len(content.title_ko) <= 100
        assert any("초과" in w for w in content.warnings)

    async def test_brand_word_stripped_into_warnings(self):
        """상품명에 상표 단어가 있으면 제거되고 warnings 에 기록."""
        router = FakeLLMRouter(translated_name="Nike 정품 무선 이어폰")
        gen = ContentGenerator(llm_router=router, category_mapper=CategoryMapper())
        content = await gen.generate(_make_ali_object())
        assert "nike" not in content.title_ko.lower()
        assert "정품" not in content.title_ko
        assert content.warnings  # 최소 하나의 경고

    async def test_brand_keyword_excluded(self):
        """위험 단어 키워드는 결과 키워드에서 제외된다."""
        router = FakeLLMRouter(keywords=["이어폰", "정품", "무선"])
        gen = ContentGenerator(llm_router=router, category_mapper=CategoryMapper())
        content = await gen.generate(_make_ali_object())
        assert "정품" not in content.keywords
        assert "이어폰" in content.keywords


# =====================================================================
# build_register_payload()
# =====================================================================


class TestBuildRegisterPayload:
    """네이버 register_product payload 조립 검증."""

    async def test_payload_structure_and_price(self, generator):
        content = await generator.generate(_make_ali_object())
        payload = generator.build_register_payload(content, price=19900)

        assert "originProduct" in payload
        origin = payload["originProduct"]
        assert origin["name"] == content.title_ko
        assert origin["salePrice"] == 19900
        assert origin["stockQuantity"] == 999  # default
        assert origin["leafCategoryId"] == content.naver_category_id
        assert origin["detailContent"] == content.description_html

    async def test_payload_images_and_tags(self, generator):
        content = await generator.generate(_make_ali_object())
        payload = generator.build_register_payload(content, price=15000)
        origin = payload["originProduct"]

        # 대표 이미지 / sellerTags 중첩 구조
        assert origin["images"]["representativeImage"]["url"] == (
            "https://img.example.com/main.jpg"
        )
        assert isinstance(origin["sellerTags"], list)
        assert origin["sellerTags"]
        assert all("text" in tag for tag in origin["sellerTags"])

    async def test_payload_custom_stock_and_extra(self, generator):
        content = await generator.generate(_make_ali_object())
        payload = generator.build_register_payload(
            content, price=10000, stock=50, deliveryInfo={"deliveryType": "DELIVERY"}
        )
        origin = payload["originProduct"]
        assert origin["stockQuantity"] == 50
        assert origin["deliveryInfo"] == {"deliveryType": "DELIVERY"}

    async def test_payload_outbound_identity_defaults_to_no_brand(self, generator):
        # Default: register under no brand so the listing stays 비매칭 단독.
        content = await generator.generate(_make_ali_object())
        origin = generator.build_register_payload(content, price=19900)["originProduct"]
        assert origin["brand"] == ""
        assert origin["manufacturer"] == ""

    async def test_payload_outbound_identity_custom_own_brand(self, generator):
        content = await generator.generate(_make_ali_object())
        origin = generator.build_register_payload(
            content, price=19900, own_brand="마이브랜드"
        )["originProduct"]
        assert origin["brand"] == "마이브랜드"
        assert origin["manufacturer"] == "마이브랜드"  # defaults to own_brand


# =====================================================================
# Construction without injected deps (no API keys needed at __init__)
# =====================================================================


class TestConstruction:
    """생성자가 API 키 없이도 구성 가능해야 한다 (지연 생성)."""

    def test_construct_without_args(self):
        """인자 없이 생성해도 예외가 발생하지 않는다 (의존성은 지연 생성)."""
        gen = ContentGenerator()
        assert gen is not None


# =====================================================================
# Detail-page fallback to the deterministic template (no LLM key)
# =====================================================================


class _RaisingDetailRouter(FakeLLMRouter):
    async def generate_detail_page(self, product_info: dict) -> str:
        raise RuntimeError("no anthropic api key")


class _EmptyDetailRouter(FakeLLMRouter):
    async def generate_detail_page(self, product_info: dict) -> str:
        return ""


class TestDetailPageFallback:
    """LLM 미설정/실패 시 결정론적 한글 템플릿으로 폴백한다."""

    async def test_falls_back_to_template_when_llm_raises(self):
        gen = ContentGenerator(llm_router=_RaisingDetailRouter(), category_mapper=CategoryMapper())
        content = await gen.generate(_make_ali_object())
        html = content.description_html
        assert 'data-sec="hook"' in html and 'data-sec="cta_review"' in html

    async def test_template_css_not_corrupted_by_avoid_words(self):
        # the template is NOT run through _strip_avoid_words, so width:100% survives
        # (AVOID_WORDS contains "100%").
        gen = ContentGenerator(llm_router=_EmptyDetailRouter(), category_mapper=CategoryMapper())
        content = await gen.generate(_make_ali_object())
        assert "width:100%" in content.description_html
