"""
DropAgent 핵심 비즈니스 로직 모듈

드롭쉬핑 자동화 시스템의 핵심 계산/평가 엔진을 제공합니다.

모듈 구성:
    - margin_calculator: 마진율 계산
    - priority_scorer: 우선순위 스코어링
    - risk_scorer: 리스크 평가
    - ops_cost_scorer: 운영 비용 평가
    - demand_estimator: 수요 추정
    - rate_limiter: API 호출 빈도 제한
    - idempotency: 중복 실행 방지
    - category_mapper: 카테고리 매핑 (알리 -> 네이버)
"""

# 마진 계산
# 카테고리 매핑
from dropagent.core.category_mapper import (
    CategoryMapper,
    NaverCategory,
)

# 콘텐츠 생성 (상세페이지)
from dropagent.core.content_generator import (
    ContentGenerator,
    GeneratedContent,
)

# 수요 추정
from dropagent.core.demand_estimator import (
    DemandEstimator,
    DemandResult,
)

# 멱등성
from dropagent.core.idempotency import (
    IdempotencyManager,
)
from dropagent.core.margin_calculator import (
    CostBreakdown,
    MarginCalculator,
    MarginResult,
)

# 운영 비용 평가
from dropagent.core.ops_cost_scorer import (
    OpsCostResult,
    OpsCostScorer,
)

# 가격 책정
from dropagent.core.pricing import (
    PricingResult,
    charm_round,
    optimal_price,
)

# 우선순위 스코어링
from dropagent.core.priority_scorer import (
    PriorityResult,
    PriorityScorer,
    ScoringWeights,
)

# 레이트 리미터
from dropagent.core.rate_limiter import (
    TokenBucketRateLimiter,
    create_naver_commerce_limiter,
    create_naver_search_limiter,
)

# 리스크 평가
from dropagent.core.risk_scorer import (
    RiskResult,
    RiskScorer,
)

__all__ = [
    # 마진 계산
    "MarginCalculator",
    "MarginResult",
    "CostBreakdown",
    # 우선순위 스코어링
    "PriorityScorer",
    "PriorityResult",
    "ScoringWeights",
    # 리스크 평가
    "RiskScorer",
    "RiskResult",
    # 운영 비용 평가
    "OpsCostScorer",
    "OpsCostResult",
    # 수요 추정
    "DemandEstimator",
    "DemandResult",
    # 레이트 리미터
    "TokenBucketRateLimiter",
    "create_naver_commerce_limiter",
    "create_naver_search_limiter",
    # 멱등성
    "IdempotencyManager",
    # 카테고리 매핑
    "CategoryMapper",
    "NaverCategory",
    # 콘텐츠 생성
    "ContentGenerator",
    "GeneratedContent",
    # 가격 책정
    "optimal_price",
    "PricingResult",
    "charm_round",
]
