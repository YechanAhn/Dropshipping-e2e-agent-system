"""
Shared fixtures for all tests.

Provides mock settings, sample data, and pre-configured scorer/calculator
instances so that tests run without any external dependencies (no real DB,
no real APIs, no .env file required).
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

# =====================================================================
# Mock settings
# =====================================================================

@pytest.fixture
def mock_settings():
    """Create mock settings that don't require .env file."""
    settings = MagicMock()
    # Database
    settings.database_url = "postgresql+asyncpg://test:test@localhost:5432/test_db"
    # Naver API
    settings.naver_client_id = "test_naver_client_id"
    settings.naver_client_secret = "test_naver_client_secret"
    settings.naver_commerce_api_key = "test_commerce_key"
    # AliExpress API
    settings.ali_app_key = "test_ali_app_key"
    settings.ali_app_secret = "test_ali_app_secret"
    # Exchange rate
    settings.default_exchange_rate = 190.0
    # Misc
    settings.environment = "test"
    settings.log_level = "DEBUG"
    return settings


# =====================================================================
# Sample product data
# =====================================================================

@pytest.fixture
def sample_product():
    """Sample AliExpress product data for testing."""
    return {
        "product_id": "ALI-12345",
        "title": "LED Ring Light with Tripod Stand",
        "ali_category": "Consumer Electronics",
        "price_cny": Decimal("55.00"),
        "shipping_cny": Decimal("8.50"),
        "exchange_rate": Decimal("190.0"),
        "weight_kg": 0.8,
        "option_count": 4,
        "has_size_chart": False,
        "review_count": 320,
        "rating": 4.7,
        "orders_count": 1500,
        "shipping_days": 15,
        "is_fragile": False,
    }


# =====================================================================
# Sample naver prices
# =====================================================================

@pytest.fixture
def sample_naver_prices():
    """Sample Naver competitor prices."""
    return [18900, 21000, 19500, 22000, 20000, 19000, 23000, 18500, 20500, 21500]


# =====================================================================
# Core calculator / scorer instances
# =====================================================================

@pytest.fixture
def margin_calculator():
    """MarginCalculator instance with default settings."""
    from dropagent.core.margin_calculator import MarginCalculator
    return MarginCalculator()


@pytest.fixture
def priority_scorer():
    """PriorityScorer instance with default weights."""
    from dropagent.core.priority_scorer import PriorityScorer
    return PriorityScorer()


@pytest.fixture
def risk_scorer():
    """RiskScorer instance with default settings."""
    from dropagent.core.risk_scorer import RiskScorer
    return RiskScorer()


@pytest.fixture
def ops_cost_scorer():
    """OpsCostScorer instance with default settings."""
    from dropagent.core.ops_cost_scorer import OpsCostScorer
    return OpsCostScorer()


@pytest.fixture
def category_mapper():
    """CategoryMapper instance with default mappings."""
    from dropagent.core.category_mapper import CategoryMapper
    return CategoryMapper()


@pytest.fixture
def demand_estimator():
    """DemandEstimator instance with default weights."""
    from dropagent.core.demand_estimator import DemandEstimator
    return DemandEstimator()


# =====================================================================
# Mock async DB session
# =====================================================================

@pytest.fixture
def mock_async_session():
    """Create a mock SQLAlchemy AsyncSession for testing."""
    session = AsyncMock()
    # Default: execute returns no existing record
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session
