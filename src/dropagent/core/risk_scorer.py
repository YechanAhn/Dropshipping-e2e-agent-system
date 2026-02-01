"""
리스크 스코어링 엔진

드롭쉬핑 상품의 다양한 리스크 요소를 평가하고 점수화합니다.

PRD 리스크 요소:
    | 요소           | 벌점               | 비고            |
    |----------------|--------------------|-----------------
    | 배송 기간      | 30+: 0.8, 20-30: 0.4 | CS 급증        |
    | 파손 리스크    | 유리/도자기: 0.9, 전자: 0.5 | 반품률     |
    | 통관 리스크    | 화장품: 0.7, 식품: 0.9, 전자: 0.4 | 규제   |
    | 무게/부피      | 2kg+: 0.5          | 배송비 급등     |

리스크 산출: 각 요소의 가중 평균, 최대 1.0
"""

from dataclasses import dataclass

from dropagent.utils.exceptions import ScoreCalculationError
from dropagent.utils.logging import get_logger

logger = get_logger(__name__)


# =====================================================================
# 카테고리별 파손 리스크 룰 테이블
# =====================================================================
FRAGILE_CATEGORY_RISKS: dict[str, float] = {
    # 깨지기 쉬운 제품
    "유리/도자기": 0.9,
    "주방용품": 0.7,
    "인테리어소품": 0.6,

    # 전자제품
    "디지털/가전": 0.5,
    "컴퓨터/주변기기": 0.5,
    "카메라/캠코더": 0.6,

    # 보통
    "주얼리/액세서리": 0.4,
    "화장품/미용": 0.3,

    # 파손 리스크 낮음
    "패션의류": 0.1,
    "패션잡화": 0.1,
    "도서": 0.05,
    "문구/오피스": 0.15,
    "생활용품": 0.2,
    "스포츠/레저": 0.2,
    "완구/취미": 0.25,
    "반려동물용품": 0.15,
}

DEFAULT_FRAGILE_RISK = 0.2

# =====================================================================
# 카테고리별 통관 리스크 룰 테이블
# =====================================================================
CUSTOMS_RISK_CATEGORIES: dict[str, float] = {
    # 높은 통관 리스크
    "식품": 0.9,
    "건강기능식품": 0.9,
    "의약외품": 0.8,
    "화장품/미용": 0.7,

    # 중간 통관 리스크
    "디지털/가전": 0.4,
    "컴퓨터/주변기기": 0.4,
    "완구/취미": 0.3,
    "반려동물용품": 0.3,

    # 낮은 통관 리스크
    "패션의류": 0.1,
    "패션잡화": 0.1,
    "주얼리/액세서리": 0.1,
    "도서": 0.0,
    "문구/오피스": 0.1,
    "생활용품": 0.1,
    "스포츠/레저": 0.15,
    "주방용품": 0.15,
    "인테리어소품": 0.1,
    "카메라/캠코더": 0.35,
}

DEFAULT_CUSTOMS_RISK = 0.2

# 리스크 요소별 기본 가중치
DEFAULT_RISK_WEIGHTS: dict[str, float] = {
    "shipping": 0.30,
    "breakage": 0.25,
    "customs": 0.25,
    "weight": 0.20,
}


@dataclass(frozen=True)
class RiskResult:
    """리스크 평가 결과"""

    score: float  # 총 리스크 점수 (0~1)
    factors: dict[str, float]  # 개별 리스크 요소 점수
    warnings: list[str]  # 경고 메시지 목록

    def get_risk_level(self) -> str:
        """
        리스크 수준을 문자열로 반환합니다.

        Returns:
            str: "LOW", "MEDIUM", "HIGH", "VERY_HIGH"
        """
        if self.score < 0.25:
            return "LOW"
        elif self.score < 0.5:
            return "MEDIUM"
        elif self.score < 0.75:
            return "HIGH"
        else:
            return "VERY_HIGH"


class RiskScorer:
    """
    리스크 스코어 계산기

    배송 기간, 파손 위험, 통관 리스크, 무게 등의 요소를
    가중 평균으로 결합하여 0~1 범위의 리스크 점수를 산출합니다.
    """

    def __init__(
        self,
        fragile_categories: dict[str, float] | None = None,
        customs_categories: dict[str, float] | None = None,
        weights: dict[str, float] | None = None,
    ) -> None:
        """
        Args:
            fragile_categories: 카테고리별 파손 리스크 딕셔너리
            customs_categories: 카테고리별 통관 리스크 딕셔너리
            weights: 리스크 요소별 가중치
                예: {"shipping": 0.3, "breakage": 0.25, "customs": 0.25, "weight": 0.2}
        """
        self.fragile_categories = fragile_categories or dict(FRAGILE_CATEGORY_RISKS)
        self.customs_categories = customs_categories or dict(CUSTOMS_RISK_CATEGORIES)
        self.weights = weights or dict(DEFAULT_RISK_WEIGHTS)
        logger.info("risk_scorer_initialized", weights=self.weights)

    # ------------------------------------------------------------------
    # 개별 리스크 요소 계산
    # ------------------------------------------------------------------

    @staticmethod
    def _shipping_risk(days: int) -> float:
        """
        배송 기간에 따른 리스크를 계산합니다.

        Args:
            days: 배송 소요 일수

        Returns:
            float: 배송 리스크 점수
                30일 이상 -> 0.8
                20~29일   -> 0.4
                10~19일   -> 0.15
                10일 미만 -> 0.05
        """
        if days >= 30:
            return 0.8
        elif days >= 20:
            return 0.4
        elif days >= 10:
            return 0.15
        else:
            return 0.05

    def _breakage_risk(self, category: str, is_fragile: bool) -> float:
        """
        파손 리스크를 계산합니다.

        명시적으로 fragile 플래그가 설정된 경우 카테고리 기본값에
        추가 패널티(0.2)를 부과합니다.

        Args:
            category: 상품 카테고리
            is_fragile: 파손 위험 여부 (수동 지정)

        Returns:
            float: 파손 리스크 점수 (0~1)
        """
        base = self.fragile_categories.get(category, DEFAULT_FRAGILE_RISK)
        if is_fragile:
            base = min(1.0, base + 0.2)
        return base

    def _customs_risk(self, category: str) -> float:
        """
        통관 리스크를 계산합니다.

        Args:
            category: 상품 카테고리

        Returns:
            float: 통관 리스크 점수 (0~1)
        """
        return self.customs_categories.get(category, DEFAULT_CUSTOMS_RISK)

    @staticmethod
    def _weight_risk(weight_kg: float) -> float:
        """
        무게에 따른 리스크를 계산합니다.

        무거운 상품일수록 배송비 급등, 파손 위험이 증가합니다.

        Args:
            weight_kg: 무게 (kg)

        Returns:
            float: 무게 리스크 점수
                2kg 이상 -> 0.5
                1~2kg    -> 0.2
                1kg 미만 -> 0.0
        """
        if weight_kg >= 2.0:
            return 0.5
        elif weight_kg >= 1.0:
            return 0.2
        else:
            return 0.0

    # ------------------------------------------------------------------
    # 경고 메시지 생성
    # ------------------------------------------------------------------

    @staticmethod
    def _build_warnings(
        shipping_days: int,
        breakage: float,
        customs: float,
        weight_kg: float,
        category: str,
    ) -> list[str]:
        """리스크 수준에 따라 경고 메시지를 생성합니다."""
        warnings: list[str] = []

        if shipping_days >= 30:
            warnings.append(
                f"배송 기간이 {shipping_days}일로 CS 급증이 예상됩니다."
            )
        elif shipping_days >= 20:
            warnings.append(
                f"배송 기간이 {shipping_days}일로 고객 불만이 발생할 수 있습니다."
            )

        if breakage >= 0.7:
            warnings.append(
                f"파손 리스크가 매우 높습니다 (카테고리: {category}, 점수: {breakage:.2f}). "
                "포장 강화 및 보험 가입을 권장합니다."
            )
        elif breakage >= 0.5:
            warnings.append(
                f"파손 리스크가 높습니다 (점수: {breakage:.2f}). 취급주의가 필요합니다."
            )

        if customs >= 0.7:
            warnings.append(
                f"통관 리스크가 매우 높습니다 (카테고리: {category}, 점수: {customs:.2f}). "
                "인증/허가 확인이 필요합니다."
            )
        elif customs >= 0.4:
            warnings.append(
                f"통관 리스크가 있습니다 (점수: {customs:.2f}). 수입 규제를 확인하세요."
            )

        if weight_kg >= 2.0:
            warnings.append(
                f"무게가 {weight_kg:.1f}kg으로 배송비 급등이 예상됩니다."
            )

        return warnings

    # ------------------------------------------------------------------
    # 통합 계산
    # ------------------------------------------------------------------

    def calculate(
        self,
        shipping_days: int,
        product_category: str,
        weight_kg: float,
        is_fragile: bool = False,
    ) -> RiskResult:
        """
        전체 리스크를 계산합니다.

        4가지 리스크 요소(배송, 파손, 통관, 무게)의 가중 평균을 산출하고
        최대 1.0으로 클리핑합니다.

        Args:
            shipping_days: 배송 소요 일수
            product_category: 상품 카테고리 (네이버 기준)
            weight_kg: 무게 (kg)
            is_fragile: 파손 위험 상품 여부 (수동 지정)

        Returns:
            RiskResult: 리스크 점수, 요소별 상세, 경고 메시지

        Raises:
            ScoreCalculationError: 리스크 계산 중 오류 발생 시

        Examples:
            >>> scorer = RiskScorer()
            >>> result = scorer.calculate(
            ...     shipping_days=25,
            ...     product_category="유리/도자기",
            ...     weight_kg=1.5,
            ...     is_fragile=True,
            ... )
            >>> result.get_risk_level()
            'HIGH'
        """
        try:
            shipping = self._shipping_risk(shipping_days)
            breakage = self._breakage_risk(product_category, is_fragile)
            customs = self._customs_risk(product_category)
            weight = self._weight_risk(weight_kg)

            factors: dict[str, float] = {
                "shipping": round(shipping, 4),
                "breakage": round(breakage, 4),
                "customs": round(customs, 4),
                "weight": round(weight, 4),
            }

            # 가중 평균 산출 (가중치 합이 1.0이 아닐 수 있으므로 정규화)
            w = self.weights
            total_weight = sum(w.values())
            if total_weight == 0:
                total_risk = 0.0
            else:
                total_risk = (
                    shipping * w.get("shipping", 0.0)
                    + breakage * w.get("breakage", 0.0)
                    + customs * w.get("customs", 0.0)
                    + weight * w.get("weight", 0.0)
                ) / total_weight

            # 0~1 클리핑
            total_risk = round(min(1.0, max(0.0, total_risk)), 4)

            warnings = self._build_warnings(
                shipping_days, breakage, customs, weight_kg, product_category
            )

            logger.debug(
                "risk_score_calculated",
                category=product_category,
                score=total_risk,
                level=RiskResult(
                    score=total_risk, factors=factors, warnings=warnings
                ).get_risk_level(),
            )

            return RiskResult(
                score=total_risk,
                factors=factors,
                warnings=warnings,
            )

        except Exception as exc:
            logger.error(
                "risk_score_calculation_failed",
                category=product_category,
                error=str(exc),
            )
            raise ScoreCalculationError(
                message=f"리스크 스코어 계산 실패: {exc}",
                metric="risk_score",
                original_error=exc,
            ) from exc

    # ------------------------------------------------------------------
    # 커스텀 카테고리 등록
    # ------------------------------------------------------------------

    def add_custom_category_risk(
        self,
        category: str,
        fragile_risk: float | None = None,
        customs_risk: float | None = None,
    ) -> None:
        """
        커스텀 카테고리의 리스크를 추가합니다.

        Args:
            category: 카테고리명
            fragile_risk: 파손 리스크 (0~1)
            customs_risk: 통관 리스크 (0~1)

        Raises:
            ValueError: 점수가 0~1 범위를 벗어난 경우
        """
        if fragile_risk is not None:
            if not (0.0 <= fragile_risk <= 1.0):
                raise ValueError(
                    f"fragile_risk는 0~1 범위여야 합니다. 입력값: {fragile_risk}"
                )
            self.fragile_categories[category] = fragile_risk

        if customs_risk is not None:
            if not (0.0 <= customs_risk <= 1.0):
                raise ValueError(
                    f"customs_risk는 0~1 범위여야 합니다. 입력값: {customs_risk}"
                )
            self.customs_categories[category] = customs_risk

        logger.info(
            "custom_category_risk_added",
            category=category,
            fragile_risk=fragile_risk,
            customs_risk=customs_risk,
        )
