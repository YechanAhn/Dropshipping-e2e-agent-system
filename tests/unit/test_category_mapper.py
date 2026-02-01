"""
Tests for CategoryMapper.

Covers:
    - Exact mapping for known categories
    - Fuzzy matching
    - Fallback for unknown categories
    - Commission rate retrieval
"""

from decimal import Decimal

from dropagent.core.category_mapper import (
    DEFAULT_NAVER_CATEGORY,
    NaverCategory,
)

# =====================================================================
# Exact mapping for known categories
# =====================================================================

class TestExactMapping:
    """Tests for exact category mapping."""

    def test_consumer_electronics(self, category_mapper):
        """Consumer Electronics maps to digital/electronics."""
        result = category_mapper.map_category("Consumer Electronics")
        assert result.name == "디지털/가전"
        assert result.commission_rate == Decimal("5.5")

    def test_womens_clothing(self, category_mapper):
        """Women's Clothing maps to fashion."""
        result = category_mapper.map_category("Women's Clothing")
        assert result.name == "패션의류"
        assert result.commission_rate == Decimal("7.0")

    def test_mens_clothing(self, category_mapper):
        """Men's Clothing maps to fashion."""
        result = category_mapper.map_category("Men's Clothing")
        assert result.name == "패션의류"

    def test_jewelry_accessories(self, category_mapper):
        """Jewelry & Accessories maps correctly."""
        result = category_mapper.map_category("Jewelry & Accessories")
        assert result.name == "주얼리/액세서리"
        assert result.commission_rate == Decimal("7.5")

    def test_case_insensitive(self, category_mapper):
        """Mapping is case-insensitive."""
        result1 = category_mapper.map_category("CONSUMER ELECTRONICS")
        result2 = category_mapper.map_category("consumer electronics")
        assert result1.name == result2.name

    def test_whitespace_trimmed(self, category_mapper):
        """Leading/trailing whitespace is trimmed."""
        result = category_mapper.map_category("  Consumer Electronics  ")
        assert result.name == "디지털/가전"

    def test_pet_products(self, category_mapper):
        """Pet Products maps correctly."""
        result = category_mapper.map_category("Pet Products")
        assert result.name == "반려동물용품"
        assert result.commission_rate == Decimal("8.0")

    def test_home_and_garden(self, category_mapper):
        """Home & Garden maps correctly."""
        result = category_mapper.map_category("Home & Garden")
        assert result.name == "생활/건강"

    def test_beauty_and_health(self, category_mapper):
        """Beauty & Health maps correctly."""
        result = category_mapper.map_category("Beauty & Health")
        assert result.name == "화장품/미용"

    def test_sports_entertainment(self, category_mapper):
        """Sports & Entertainment maps correctly."""
        result = category_mapper.map_category("Sports & Entertainment")
        assert result.name == "스포츠/레저"


# =====================================================================
# Fuzzy matching
# =====================================================================

class TestFuzzyMatching:
    """Tests for keyword-based fuzzy matching."""

    def test_dress_keyword(self, category_mapper):
        """A category containing 'dress' fuzzy-matches to women's clothing."""
        result = category_mapper.map_category("Summer Dress Collection")
        assert result.name == "패션의류"

    def test_shoe_keyword(self, category_mapper):
        """A category containing 'shoe' fuzzy-matches to shoes."""
        result = category_mapper.map_category("Running Shoe Accessories")
        assert result.name == "패션잡화"

    def test_phone_keyword(self, category_mapper):
        """A category containing 'phone' fuzzy-matches to electronics."""
        result = category_mapper.map_category("Phone Cases and Covers")
        assert result.name == "디지털/가전"

    def test_ring_keyword(self, category_mapper):
        """A category containing 'ring' fuzzy-matches to jewelry."""
        result = category_mapper.map_category("Diamond Ring Gold")
        assert result.name == "주얼리/액세서리"

    def test_pet_keyword(self, category_mapper):
        """A category containing 'pet' fuzzy-matches to pet products."""
        result = category_mapper.map_category("Pet Grooming Supplies")
        assert result.name == "반려동물용품"

    def test_toy_keyword(self, category_mapper):
        """A category containing 'toy' fuzzy-matches to toys/hobbies."""
        result = category_mapper.map_category("Educational Toy for Kids")
        assert result.name == "완구/취미"

    def test_laptop_keyword(self, category_mapper):
        """A category containing 'laptop' fuzzy-matches to computers."""
        result = category_mapper.map_category("Laptop Stand Holder")
        assert result.name == "컴퓨터/주변기기"

    def test_makeup_keyword(self, category_mapper):
        """A category containing 'makeup' fuzzy-matches to beauty."""
        result = category_mapper.map_category("Makeup Brush Set Professional")
        assert result.name == "화장품/미용"


# =====================================================================
# Fallback for unknown categories
# =====================================================================

class TestFallbackCategory:
    """Tests for fallback to default category."""

    def test_completely_unknown_category(self, category_mapper):
        """Completely unrecognizable category falls back to default."""
        result = category_mapper.map_category("Xyzzy Quantum Flux Capacitor")
        assert result == DEFAULT_NAVER_CATEGORY
        assert result.name == "기타"
        assert result.commission_rate == Decimal("8.0")

    def test_empty_string(self, category_mapper):
        """Empty string maps to default category."""
        result = category_mapper.map_category("")
        assert result == DEFAULT_NAVER_CATEGORY

    def test_numeric_string(self, category_mapper):
        """Numeric-only string maps to default category."""
        result = category_mapper.map_category("12345")
        assert result == DEFAULT_NAVER_CATEGORY

    def test_default_category_has_valid_id(self):
        """Default category has a valid category ID."""
        assert DEFAULT_NAVER_CATEGORY.id == "50099999"


# =====================================================================
# Commission rate retrieval
# =====================================================================

class TestCommissionRetrieval:
    """Tests for get_naver_commission() and get_naver_commission_as_ratio()."""

    def test_get_commission_for_known_category(self, category_mapper):
        """get_naver_commission returns percentage rate."""
        rate = category_mapper.get_naver_commission("Consumer Electronics")
        assert rate == Decimal("5.5")

    def test_get_commission_for_unknown_category(self, category_mapper):
        """Unknown category returns default 8.0% commission."""
        rate = category_mapper.get_naver_commission("Unknown Category XYZ")
        assert rate == Decimal("8.0")

    def test_get_commission_as_ratio(self, category_mapper):
        """get_naver_commission_as_ratio returns decimal ratio."""
        ratio = category_mapper.get_naver_commission_as_ratio("Consumer Electronics")
        assert ratio == Decimal("0.0550")

    def test_get_commission_as_ratio_fashion(self, category_mapper):
        """Fashion commission as ratio is 0.0700."""
        ratio = category_mapper.get_naver_commission_as_ratio("Women's Clothing")
        assert ratio == Decimal("0.0700")

    def test_get_commission_as_ratio_unknown(self, category_mapper):
        """Unknown category commission as ratio is 0.0800."""
        ratio = category_mapper.get_naver_commission_as_ratio("Unknown XYZ")
        assert ratio == Decimal("0.0800")


# =====================================================================
# Custom mapping management
# =====================================================================

class TestCustomMappingManagement:
    """Tests for add_mapping() and list_mappings()."""

    def test_add_custom_mapping(self, category_mapper):
        """Added custom mapping is used for exact match."""
        custom = NaverCategory(
            id="59999999",
            name="커스텀카테고리",
            commission_rate=Decimal("6.0"),
        )
        category_mapper.add_mapping("My Custom Category", custom)
        result = category_mapper.map_category("My Custom Category")
        assert result.name == "커스텀카테고리"
        assert result.commission_rate == Decimal("6.0")

    def test_add_mapping_normalizes_key(self, category_mapper):
        """add_mapping normalizes the key to lowercase."""
        custom = NaverCategory(
            id="59999999",
            name="테스트",
            commission_rate=Decimal("5.0"),
        )
        category_mapper.add_mapping("  UPPER CASE  ", custom)
        result = category_mapper.map_category("upper case")
        assert result.name == "테스트"

    def test_list_mappings_returns_dict(self, category_mapper):
        """list_mappings returns a copy of all mappings."""
        mappings = category_mapper.list_mappings()
        assert isinstance(mappings, dict)
        assert len(mappings) > 0
        # Verify it's a copy (not same reference)
        assert mappings is not category_mapper._mappings

    def test_override_existing_mapping(self, category_mapper):
        """Adding a mapping for an existing key overrides it."""
        custom = NaverCategory(
            id="99999999",
            name="오버라이드",
            commission_rate=Decimal("3.0"),
        )
        category_mapper.add_mapping("Consumer Electronics", custom)
        result = category_mapper.map_category("Consumer Electronics")
        assert result.name == "오버라이드"
        assert result.commission_rate == Decimal("3.0")
