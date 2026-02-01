"""
알리익스프레스 → 네이버 스마트스토어 카테고리 매핑

알리익스프레스 카테고리를 네이버 스마트스토어 카테고리로 매핑합니다.

주요 기능:
    - 정확한 매핑: 사전 정의된 매핑 테이블 (20+ 카테고리)
    - 퍼지 매칭: 키워드 기반 유사 카테고리 탐색
    - 수수료 조회: 네이버 카테고리별 수수료율 반환
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from dropagent.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class NaverCategory:
    """네이버 스마트스토어 카테고리"""

    id: str  # 네이버 카테고리 ID
    name: str  # 카테고리명 (한글)
    commission_rate: Decimal  # 수수료율 (%, 예: Decimal("7.0"))


# =====================================================================
# 알리익스프레스 → 네이버 매핑 테이블
# =====================================================================
# key: 알리 카테고리 (영문, 소문자 정규화됨)
# value: NaverCategory

_CATEGORY_MAPPINGS: dict[str, NaverCategory] = {
    # ---- 패션 / 의류 ----
    "women's clothing": NaverCategory(
        id="50000000", name="패션의류", commission_rate=Decimal("7.0")
    ),
    "men's clothing": NaverCategory(
        id="50000001", name="패션의류", commission_rate=Decimal("7.0")
    ),
    "women's shoes": NaverCategory(
        id="50000010", name="패션잡화", commission_rate=Decimal("7.0")
    ),
    "men's shoes": NaverCategory(
        id="50000011", name="패션잡화", commission_rate=Decimal("7.0")
    ),
    "underwear & loungewear": NaverCategory(
        id="50000002", name="패션의류", commission_rate=Decimal("7.0")
    ),
    "kids & babies": NaverCategory(
        id="50000030", name="출산/육아", commission_rate=Decimal("8.5")
    ),

    # ---- 액세서리 / 주얼리 ----
    "jewelry & accessories": NaverCategory(
        id="50000020", name="주얼리/액세서리", commission_rate=Decimal("7.5")
    ),
    "watches": NaverCategory(
        id="50000021", name="주얼리/액세서리", commission_rate=Decimal("7.5")
    ),
    "bags & luggage": NaverCategory(
        id="50000012", name="패션잡화", commission_rate=Decimal("7.0")
    ),

    # ---- 전자제품 / 가전 ----
    "consumer electronics": NaverCategory(
        id="50000100", name="디지털/가전", commission_rate=Decimal("5.5")
    ),
    "phones & telecommunications": NaverCategory(
        id="50000101", name="디지털/가전", commission_rate=Decimal("5.5")
    ),
    "computer & office": NaverCategory(
        id="50000102", name="컴퓨터/주변기기", commission_rate=Decimal("5.5")
    ),
    "electronic components & supplies": NaverCategory(
        id="50000103", name="디지털/가전", commission_rate=Decimal("5.5")
    ),

    # ---- 스포츠 / 레저 ----
    "sports & entertainment": NaverCategory(
        id="50000200", name="스포츠/레저", commission_rate=Decimal("8.0")
    ),
    "outdoor fun & sports": NaverCategory(
        id="50000201", name="스포츠/레저", commission_rate=Decimal("8.0")
    ),

    # ---- 뷰티 / 건강 ----
    "beauty & health": NaverCategory(
        id="50000300", name="화장품/미용", commission_rate=Decimal("8.0")
    ),
    "hair extensions & wigs": NaverCategory(
        id="50000301", name="화장품/미용", commission_rate=Decimal("8.0")
    ),

    # ---- 홈 / 가구 ----
    "home & garden": NaverCategory(
        id="50000400", name="생활/건강", commission_rate=Decimal("9.0")
    ),
    "home improvement & tools": NaverCategory(
        id="50000401", name="생활/건강", commission_rate=Decimal("9.0")
    ),
    "furniture": NaverCategory(
        id="50000402", name="가구/인테리어", commission_rate=Decimal("9.0")
    ),
    "home appliances": NaverCategory(
        id="50000403", name="디지털/가전", commission_rate=Decimal("5.5")
    ),

    # ---- 기타 ----
    "toys & hobbies": NaverCategory(
        id="50000500", name="완구/취미", commission_rate=Decimal("7.5")
    ),
    "automobiles & motorcycles": NaverCategory(
        id="50000600", name="자동차용품", commission_rate=Decimal("7.0")
    ),
    "lights & lighting": NaverCategory(
        id="50000700", name="인테리어소품", commission_rate=Decimal("9.0")
    ),
    "pet products": NaverCategory(
        id="50000800", name="반려동물용품", commission_rate=Decimal("8.0")
    ),
    "office & school supplies": NaverCategory(
        id="50000900", name="문구/오피스", commission_rate=Decimal("8.0")
    ),
}

# 기본 카테고리 (매핑 실패 시 사용)
DEFAULT_NAVER_CATEGORY = NaverCategory(
    id="50099999", name="기타", commission_rate=Decimal("8.0")
)

# =====================================================================
# 퍼지 매칭용 키워드 → 네이버 카테고리 매핑
# =====================================================================
# 각 키워드는 입력 문자열의 *단어*(공백/특수문자로 분리)와 비교합니다.
# 멀티워드 키워드(예: "skin care")는 부분 문자열로도 매칭됩니다.
_KEYWORD_MAPPINGS: list[tuple[list[str], str]] = [
    # (키워드 리스트, _CATEGORY_MAPPINGS 의 key)
    (["dress", "shirt", "blouse", "skirt", "pants", "coat", "jacket",
      "sweater", "hoodie", "clothing", "apparel", "fashion"],
     "women's clothing"),
    (["shoe", "shoes", "boot", "boots", "sandal", "sneaker", "slipper"],
     "women's shoes"),
    (["bag", "bags", "backpack", "wallet", "luggage", "purse", "handbag"],
     "bags & luggage"),
    (["ring", "necklace", "bracelet", "earring", "jewelry", "jewellery"],
     "jewelry & accessories"),
    (["watch", "watches", "smartwatch"],
     "watches"),
    (["phone", "mobile", "tablet", "telecommunication", "cellphone"],
     "phones & telecommunications"),
    (["computer", "laptop", "keyboard", "monitor", "office equipment"],
     "computer & office"),
    (["electronic", "electronics", "gadget", "headphone", "earphone",
      "speaker", "audio", "camera", "video", "television"],
     "consumer electronics"),
    (["sport", "sports", "fitness", "gym", "yoga", "cycling", "running", "outdoor"],
     "sports & entertainment"),
    (["beauty", "makeup", "cosmetic", "skincare", "skin care", "nail art"],
     "beauty & health"),
    (["hair extension", "wig", "wigs", "hairpiece"],
     "hair extensions & wigs"),
    (["home", "kitchen", "bathroom", "garden", "bedding", "curtain"],
     "home & garden"),
    (["furniture", "sofa", "shelf", "cabinet", "bookcase"],
     "furniture"),
    (["tool", "tools", "drill", "hardware", "improvement"],
     "home improvement & tools"),
    (["toy", "toys", "hobby", "doll", "puzzle", "lego"],
     "toys & hobbies"),
    (["automobile", "motorcycle", "vehicle", "automotive"],
     "automobiles & motorcycles"),
    (["lamp", "bulb", "chandelier", "lighting"],
     "lights & lighting"),
    (["pet", "pets", "dog", "puppy", "kitten", "aquarium", "pet food"],
     "pet products"),
    (["stationery", "school supply", "office supply"],
     "office & school supplies"),
    (["baby", "infant", "toddler", "maternity"],
     "kids & babies"),
    (["appliance", "vacuum", "blender", "air conditioner", "heater"],
     "home appliances"),
]


class CategoryMapper:
    """
    알리익스프레스 → 네이버 스마트스토어 카테고리 매퍼

    정확한 매핑 → 퍼지 키워드 매칭 → 기본 카테고리 순서로 매핑을 시도합니다.
    """

    def __init__(
        self,
        custom_mappings: dict[str, NaverCategory] | None = None,
    ) -> None:
        """
        Args:
            custom_mappings: 추가/덮어쓸 카테고리 매핑 딕셔너리
                key: 알리 카테고리명 (소문자)
                value: NaverCategory
        """
        self._mappings: dict[str, NaverCategory] = dict(_CATEGORY_MAPPINGS)
        if custom_mappings:
            self._mappings.update(custom_mappings)

        self._keyword_map: list[tuple[list[str], str]] = list(_KEYWORD_MAPPINGS)

        logger.info(
            "category_mapper_initialized",
            mapping_count=len(self._mappings),
        )

    # ------------------------------------------------------------------
    # 정확한 매핑
    # ------------------------------------------------------------------

    def _exact_match(self, ali_category: str) -> NaverCategory | None:
        """알리 카테고리명의 정확한 매핑을 시도합니다."""
        normalized = ali_category.strip().lower()
        return self._mappings.get(normalized)

    # ------------------------------------------------------------------
    # 퍼지 매칭 (키워드 기반)
    # ------------------------------------------------------------------

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """텍스트를 소문자 단어 토큰 집합으로 분리합니다."""
        import re
        return set(re.findall(r"[a-z]+", text.lower()))

    def _fuzzy_match(self, ali_category: str) -> NaverCategory | None:
        """
        키워드 기반 퍼지 매칭을 시도합니다.

        입력 카테고리명을 단어 토큰으로 분리한 뒤,
        각 키워드 규칙의 매칭 횟수를 세어 가장 많이 일치하는 카테고리를 선택합니다.

        - 단일 단어 키워드: 입력 토큰 집합에 포함되어야 매칭
        - 멀티 단어 키워드(공백 포함): 입력 문자열의 부분 문자열로 매칭

        이 방식으로 "cat"이 "category"에 매칭되는 문제를 방지합니다.
        """
        normalized = ali_category.strip().lower()
        input_tokens = self._tokenize(normalized)

        best_match_key: str | None = None
        best_match_count = 0

        for keywords, mapping_key in self._keyword_map:
            match_count = 0
            for kw in keywords:
                if " " in kw:
                    # 멀티 단어 키워드: 부분 문자열 매칭
                    if kw in normalized:
                        match_count += 1
                else:
                    # 단일 단어 키워드: 토큰 매칭
                    if kw in input_tokens:
                        match_count += 1

            if match_count > best_match_count:
                best_match_count = match_count
                best_match_key = mapping_key

        if best_match_key is not None and best_match_count > 0:
            result = self._mappings.get(best_match_key)
            if result is not None:
                logger.debug(
                    "category_fuzzy_matched",
                    ali_category=ali_category,
                    matched_key=best_match_key,
                    naver_category=result.name,
                    keyword_hits=best_match_count,
                )
                return result

        return None

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def map_category(self, ali_category: str) -> NaverCategory:
        """
        알리익스프레스 카테고리를 네이버 스마트스토어 카테고리로 매핑합니다.

        매핑 순서:
            1. 정확한 매핑 (사전 테이블)
            2. 퍼지 키워드 매칭
            3. 기본 카테고리 ("기타")

        Args:
            ali_category: 알리익스프레스 카테고리명 (영문)

        Returns:
            NaverCategory: 매핑된 네이버 카테고리 (id, name, commission_rate)

        Examples:
            >>> mapper = CategoryMapper()
            >>> result = mapper.map_category("Consumer Electronics")
            >>> result.name
            '디지털/가전'
            >>> result.commission_rate
            Decimal('5.5')
        """
        # 1) 정확한 매핑
        result = self._exact_match(ali_category)
        if result is not None:
            logger.debug(
                "category_exact_matched",
                ali_category=ali_category,
                naver_category=result.name,
            )
            return result

        # 2) 퍼지 매칭
        result = self._fuzzy_match(ali_category)
        if result is not None:
            return result

        # 3) 기본 카테고리
        logger.warning(
            "category_mapping_fallback",
            ali_category=ali_category,
            default_category=DEFAULT_NAVER_CATEGORY.name,
        )
        return DEFAULT_NAVER_CATEGORY

    def get_naver_commission(self, ali_category: str) -> Decimal:
        """
        알리익스프레스 카테고리에 해당하는 네이버 수수료율을 반환합니다.

        Args:
            ali_category: 알리익스프레스 카테고리명 (영문)

        Returns:
            Decimal: 수수료율 (%, 예: Decimal("5.5"))

        Examples:
            >>> mapper = CategoryMapper()
            >>> mapper.get_naver_commission("Computer & Office")
            Decimal('5.5')
            >>> mapper.get_naver_commission("Unknown Category")
            Decimal('8.0')
        """
        naver = self.map_category(ali_category)
        return naver.commission_rate

    def get_naver_commission_as_ratio(self, ali_category: str) -> Decimal:
        """
        수수료율을 비율(소수)로 반환합니다.

        Args:
            ali_category: 알리익스프레스 카테고리명

        Returns:
            Decimal: 수수료 비율 (예: 0.055 = 5.5%)
        """
        rate_pct = self.get_naver_commission(ali_category)
        return (rate_pct / Decimal("100")).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )

    # ------------------------------------------------------------------
    # 매핑 관리
    # ------------------------------------------------------------------

    def add_mapping(self, ali_category: str, naver_category: NaverCategory) -> None:
        """
        커스텀 카테고리 매핑을 추가합니다.

        Args:
            ali_category: 알리익스프레스 카테고리명 (소문자로 정규화됨)
            naver_category: 네이버 카테고리 정보
        """
        key = ali_category.strip().lower()
        self._mappings[key] = naver_category
        logger.info(
            "category_mapping_added",
            ali_category=key,
            naver_category=naver_category.name,
        )

    def list_mappings(self) -> dict[str, NaverCategory]:
        """
        현재 등록된 모든 매핑을 반환합니다.

        Returns:
            Dict[str, NaverCategory]: 알리 카테고리 -> 네이버 카테고리 매핑
        """
        return dict(self._mappings)
