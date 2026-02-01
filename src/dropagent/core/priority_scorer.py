"""
우선순위 스코어링 엔진

PRD v2에 정의된 가중치 기반 우선순위 스코어를 계산합니다.

공식:
    priority_score = (
        w1 * margin_score        # 마진율 (0~1)
        + w2 * demand_score      # 수요 점수 (0~1)
        - w3 * risk_score        # 리스크 감점 (0~1)
        - w4 * ops_cost_score    # 운영비용 감점 (0~1)
        + w5 * supplier_reliability  # 공급자 신뢰도 (0~1)
    )

기본 가중치:
    w1 (margin) = 0.35
    w2 (demand) = 0.25
    w3 (risk) = 0.15
    w4 (ops_cost) = 0.15
    w5 (supplier) = 0.10

등급 기준:
    S: > 0.8
    A: > 0.6
    B: > 0.4
    C: > 0.2
    D: <= 0.2
"""

from dataclasses import dataclass

from dropagent.utils.exceptions import ScoreCalculationError
from dropagent.utils.logging import get_logger

logger = get_logger(__name__)

# 등급 임계값 (내림차순)
RANK_THRESHOLDS: list[tuple[float, str]] = [
    (0.8, "S"),
    (0.6, "A"),
    (0.4, "B"),
    (0.2, "C"),
]
DEFAULT_RANK = "D"


@dataclass(frozen=True)
class ScoringWeights:
    """우선순위 스코어링 가중치"""

    w1_margin: float = 0.35
    w2_demand: float = 0.25
    w3_risk: float = 0.15
    w4_ops_cost: float = 0.15
    w5_supplier: float = 0.10

    def __post_init__(self) -> None:
        """가중치 합이 1.0에 가까운지 검증합니다."""
        total = (
            self.w1_margin
            + self.w2_demand
            + self.w3_risk
            + self.w4_ops_cost
            + self.w5_supplier
        )
        if not (0.99 <= total <= 1.01):
            raise ValueError(
                f"가중치 합은 1.0에 가까워야 합니다. 현재 합: {total:.4f}. "
                f"가중치: margin={self.w1_margin}, demand={self.w2_demand}, "
                f"risk={self.w3_risk}, ops_cost={self.w4_ops_cost}, "
                f"supplier={self.w5_supplier}"
            )
        for name, val in [
            ("w1_margin", self.w1_margin),
            ("w2_demand", self.w2_demand),
            ("w3_risk", self.w3_risk),
            ("w4_ops_cost", self.w4_ops_cost),
            ("w5_supplier", self.w5_supplier),
        ]:
            if val < 0:
                raise ValueError(f"가중치는 음수가 될 수 없습니다: {name}={val}")


@dataclass(frozen=True)
class PriorityResult:
    """우선순위 스코어 계산 결과"""

    score: float  # 최종 우선순위 점수 (0~1)
    rank_label: str  # 등급 (S/A/B/C/D)
    breakdown: dict[str, float]  # 구성 항목별 가중치 적용 점수

    product_id: str | None = None  # 배치 계산 시 상품 식별자


def _determine_rank(score: float) -> str:
    """
    점수에 해당하는 등급을 결정합니다.

    Args:
        score: 우선순위 점수 (0~1)

    Returns:
        str: 등급 라벨 (S/A/B/C/D)
    """
    for threshold, label in RANK_THRESHOLDS:
        if score > threshold:
            return label
    return DEFAULT_RANK


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """값을 지정된 범위로 클리핑합니다."""
    return max(low, min(high, value))


class PriorityScorer:
    """
    우선순위 스코어 계산기

    PRD v2에 정의된 가중 합산 공식을 사용하여
    상품의 소싱 우선순위를 0~1 범위의 점수로 산출합니다.
    """

    def __init__(self, weights: ScoringWeights | None = None) -> None:
        """
        Args:
            weights: 스코어링 가중치 (기본값: PRD v2 기본 가중치)
        """
        self.weights = weights or ScoringWeights()
        logger.info(
            "priority_scorer_initialized",
            w1_margin=self.weights.w1_margin,
            w2_demand=self.weights.w2_demand,
            w3_risk=self.weights.w3_risk,
            w4_ops_cost=self.weights.w4_ops_cost,
            w5_supplier=self.weights.w5_supplier,
        )

    # ------------------------------------------------------------------
    # 유틸리티
    # ------------------------------------------------------------------

    @staticmethod
    def normalize(
        value: float | int,
        min_val: float | int = 0.0,
        max_val: float | int = 1.0,
    ) -> float:
        """
        값을 0~1 범위로 정규화합니다.

        Args:
            value: 정규화할 값
            min_val: 최솟값
            max_val: 최댓값

        Returns:
            float: 정규화된 값 (0~1)

        Examples:
            >>> PriorityScorer.normalize(50, 0, 100)
            0.5
        """
        if max_val == min_val:
            return 0.5
        normalized = (float(value) - float(min_val)) / (float(max_val) - float(min_val))
        return _clamp(normalized)

    # ------------------------------------------------------------------
    # 단건 계산
    # ------------------------------------------------------------------

    def calculate(
        self,
        margin_score: float | int,
        demand_score: float | int,
        risk_score: float | int,
        ops_cost_score: float | int,
        supplier_reliability: float | int,
        product_id: str | None = None,
    ) -> PriorityResult:
        """
        우선순위 스코어를 계산합니다.

        모든 입력 값은 0~1 범위여야 합니다.
        범위 밖의 값은 자동으로 클리핑됩니다.

        - margin_score: 높을수록 좋음
        - demand_score: 높을수록 좋음
        - risk_score: 낮을수록 좋음 (감점 요소)
        - ops_cost_score: 낮을수록 좋음 (감점 요소)
        - supplier_reliability: 높을수록 좋음

        Args:
            margin_score: 마진 점수 (0~1)
            demand_score: 수요 점수 (0~1)
            risk_score: 리스크 점수 (0~1, 감점 요소)
            ops_cost_score: 운영비용 점수 (0~1, 감점 요소)
            supplier_reliability: 공급자 신뢰도 점수 (0~1)
            product_id: 상품 식별자 (선택, 배치 계산 시 사용)

        Returns:
            PriorityResult: 스코어, 등급, 구성 항목 상세

        Raises:
            ScoreCalculationError: 스코어 계산 중 오류 발생 시

        Examples:
            >>> scorer = PriorityScorer()
            >>> result = scorer.calculate(
            ...     margin_score=0.8,
            ...     demand_score=0.6,
            ...     risk_score=0.2,
            ...     ops_cost_score=0.3,
            ...     supplier_reliability=0.7,
            ... )
            >>> result.rank_label
            'A'
        """
        try:
            # 입력값 0~1 클리핑
            m = _clamp(float(margin_score))
            d = _clamp(float(demand_score))
            r = _clamp(float(risk_score))
            o = _clamp(float(ops_cost_score))
            s = _clamp(float(supplier_reliability))

            w = self.weights

            # 가중치 적용
            weighted_margin = w.w1_margin * m
            weighted_demand = w.w2_demand * d
            weighted_risk = w.w3_risk * r
            weighted_ops_cost = w.w4_ops_cost * o
            weighted_supplier = w.w5_supplier * s

            # 최종 점수 (risk, ops_cost 는 감점)
            raw_score = (
                weighted_margin
                + weighted_demand
                - weighted_risk
                - weighted_ops_cost
                + weighted_supplier
            )
            final_score = round(_clamp(raw_score), 4)

            breakdown: dict[str, float] = {
                "margin_score": round(m, 4),
                "demand_score": round(d, 4),
                "risk_score": round(r, 4),
                "ops_cost_score": round(o, 4),
                "supplier_reliability": round(s, 4),
                "weighted_margin": round(weighted_margin, 4),
                "weighted_demand": round(weighted_demand, 4),
                "weighted_risk": round(weighted_risk, 4),
                "weighted_ops_cost": round(weighted_ops_cost, 4),
                "weighted_supplier": round(weighted_supplier, 4),
            }

            rank_label = _determine_rank(final_score)

            logger.debug(
                "priority_score_calculated",
                product_id=product_id,
                score=final_score,
                rank=rank_label,
            )

            return PriorityResult(
                score=final_score,
                rank_label=rank_label,
                breakdown=breakdown,
                product_id=product_id,
            )

        except Exception as exc:
            logger.error(
                "priority_score_calculation_failed",
                product_id=product_id,
                error=str(exc),
            )
            raise ScoreCalculationError(
                message=f"우선순위 스코어 계산 실패: {exc}",
                product_id=product_id,
                metric="priority_score",
                original_error=exc,
            ) from exc

    # ------------------------------------------------------------------
    # 배치 계산
    # ------------------------------------------------------------------

    def batch_calculate(
        self,
        products: list[dict[str, float | int | str]],
    ) -> list[PriorityResult]:
        """
        여러 상품의 우선순위 스코어를 일괄 계산하고 점수 내림차순으로 정렬합니다.

        각 딕셔너리에는 다음 키가 필요합니다:
        - margin_score (float)
        - demand_score (float)
        - risk_score (float)
        - ops_cost_score (float)
        - supplier_reliability (float)
        - product_id (str, 선택)

        Args:
            products: 상품별 점수 딕셔너리 리스트

        Returns:
            List[PriorityResult]: 점수 내림차순으로 정렬된 결과 리스트

        Raises:
            ScoreCalculationError: 계산 중 오류 발생 시

        Examples:
            >>> scorer = PriorityScorer()
            >>> results = scorer.batch_calculate([
            ...     {"margin_score": 0.9, "demand_score": 0.7,
            ...      "risk_score": 0.1, "ops_cost_score": 0.2,
            ...      "supplier_reliability": 0.8, "product_id": "P001"},
            ...     {"margin_score": 0.4, "demand_score": 0.3,
            ...      "risk_score": 0.6, "ops_cost_score": 0.7,
            ...      "supplier_reliability": 0.5, "product_id": "P002"},
            ... ])
            >>> results[0].product_id
            'P001'
        """
        if not products:
            return []

        logger.info("batch_priority_scoring_started", count=len(products))

        results: list[PriorityResult] = []
        errors: list[str] = []

        for idx, product in enumerate(products):
            try:
                result = self.calculate(
                    margin_score=product.get("margin_score", 0.0),
                    demand_score=product.get("demand_score", 0.0),
                    risk_score=product.get("risk_score", 0.0),
                    ops_cost_score=product.get("ops_cost_score", 0.0),
                    supplier_reliability=product.get("supplier_reliability", 0.0),
                    product_id=product.get("product_id"),
                )
                results.append(result)
            except ScoreCalculationError as exc:
                pid = product.get("product_id", f"index-{idx}")
                errors.append(f"{pid}: {exc.message}")
                logger.warning(
                    "batch_item_skipped",
                    product_id=pid,
                    error=str(exc),
                )

        # 점수 내림차순 정렬
        results.sort(key=lambda r: r.score, reverse=True)

        logger.info(
            "batch_priority_scoring_completed",
            total=len(products),
            scored=len(results),
            errors=len(errors),
        )

        return results
