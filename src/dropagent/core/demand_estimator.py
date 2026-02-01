"""
수요 추정 엔진

판매량 데이터가 없는 드롭쉬핑 환경에서 다중 프록시 지표를
결합하여 수요를 추정합니다.

PRD 수요 점수 공식:
    DemandScore = f(
        keyword_search_volume,   # Priority 1 - 가장 직접적인 수요 지표
        review_growth_rate,      # Priority 2 - 구매자의 3~10%가 리뷰 작성
        click_trend,             # Priority 3 - DataLab 상대 지수
        own_data,                # Priority 4 - Phase 3+ 교차 검증
    )

기본 가중치:
    검색량 = 0.40
    리뷰 증가율 = 0.30
    클릭 추이 = 0.30

신뢰도:
    - 모든 지표가 있으면 HIGH(0.9)
    - 검색량 + 리뷰만 있으면 MEDIUM(0.6)
    - 검색량만 있으면 LOW(0.35)
"""

from dataclasses import dataclass

from dropagent.utils.exceptions import ScoreCalculationError
from dropagent.utils.logging import get_logger

logger = get_logger(__name__)

# 정규화 기본 임계값
DEFAULT_THRESHOLDS: dict[str, dict[str, float]] = {
    "search_volume": {"min": 0, "max": 100_000},
    "review_growth_rate": {"min": 0.0, "max": 2.0},
    "click_trend_ratio": {"min": 0.0, "max": 1.0},
}


@dataclass(frozen=True)
class DemandResult:
    """수요 추정 결과"""

    score: float  # 최종 수요 점수 (0~1)
    confidence: float  # 추정 신뢰도 (0~1)
    components: dict[str, float]  # 개별 지표 정규화 점수 및 메타

    def get_demand_level(self) -> str:
        """
        수요 수준을 문자열로 반환합니다.

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


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """값을 지정된 범위로 클리핑합니다."""
    return max(low, min(high, value))


class DemandEstimator:
    """
    수요 추정기

    키워드 검색량, 리뷰 증가율, 클릭 추이를 정규화한 뒤
    가중 평균으로 결합하여 0~1 범위의 수요 점수를 산출합니다.
    """

    def __init__(
        self,
        search_volume_weight: float = 0.40,
        review_growth_weight: float = 0.30,
        click_trend_weight: float = 0.30,
        thresholds: dict[str, dict[str, float]] | None = None,
    ) -> None:
        """
        Args:
            search_volume_weight: 검색량 가중치 (기본값: 0.40)
            review_growth_weight: 리뷰 증가율 가중치 (기본값: 0.30)
            click_trend_weight: 클릭 추이 가중치 (기본값: 0.30)
            thresholds: 각 지표의 정규화 임계값
                예: {"search_volume": {"min": 0, "max": 50000}, ...}
        """
        self.search_weight = search_volume_weight
        self.review_weight = review_growth_weight
        self.click_weight = click_trend_weight

        # 가중치 합 검증
        total_weight = self.search_weight + self.review_weight + self.click_weight
        if not (0.99 <= total_weight <= 1.01):
            raise ValueError(
                f"가중치 합은 1.0에 가까워야 합니다. 현재 합: {total_weight:.4f}"
            )

        self.thresholds = thresholds or dict(DEFAULT_THRESHOLDS)

        logger.info(
            "demand_estimator_initialized",
            search_weight=self.search_weight,
            review_weight=self.review_weight,
            click_weight=self.click_weight,
        )

    # ------------------------------------------------------------------
    # 정규화 헬퍼
    # ------------------------------------------------------------------

    def _normalize_search_volume(self, volume: int) -> float:
        """
        키워드 검색량을 0~1 범위로 정규화합니다.

        min-max 정규화를 사용하며, 설정된 max를 초과하면 1.0으로 클리핑합니다.

        Args:
            volume: 월간 검색량

        Returns:
            float: 정규화된 검색량 점수 (0~1)
        """
        t = self.thresholds.get("search_volume", DEFAULT_THRESHOLDS["search_volume"])
        min_v = t["min"]
        max_v = t["max"]
        if max_v == min_v:
            return 0.5
        return _clamp((volume - min_v) / (max_v - min_v))

    def _normalize_review_growth(self, rate: float) -> float:
        """
        리뷰 증가율을 0~1 범위로 정규화합니다.

        Args:
            rate: 리뷰 증가율 (예: 0.5 = 50% 증가)
                  음수(감소)는 0으로 클리핑

        Returns:
            float: 정규화된 리뷰 증가율 점수 (0~1)
        """
        t = self.thresholds.get(
            "review_growth_rate", DEFAULT_THRESHOLDS["review_growth_rate"]
        )
        min_v = t["min"]
        max_v = t["max"]
        if max_v == min_v:
            return 0.5
        return _clamp((rate - min_v) / (max_v - min_v))

    def _normalize_click_trend(self, ratio: float) -> float:
        """
        클릭 추이 비율을 0~1 범위로 정규화합니다.

        DataLab에서 제공하는 상대 지수(0~1 또는 0~100)를
        0~1 범위로 변환합니다.

        Args:
            ratio: 클릭 추이 비율 (0~1)

        Returns:
            float: 정규화된 클릭 추이 점수 (0~1)
        """
        t = self.thresholds.get(
            "click_trend_ratio", DEFAULT_THRESHOLDS["click_trend_ratio"]
        )
        min_v = t["min"]
        max_v = t["max"]
        if max_v == min_v:
            return 0.5
        return _clamp((ratio - min_v) / (max_v - min_v))

    # ------------------------------------------------------------------
    # 신뢰도 산출
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_confidence(
        keyword_search_volume: int,
        review_count: int | None,
        review_growth_rate: float | None,
        click_trend_ratio: float | None,
    ) -> float:
        """
        입력 데이터 가용성에 따라 추정 신뢰도를 결정합니다.

        Returns:
            float: 신뢰도 (0~1)
                - 모든 지표 존재: 0.9
                - 검색량 + 리뷰: 0.6
                - 검색량만: 0.35
        """
        has_search = keyword_search_volume > 0
        has_review = (
            review_count is not None
            and review_count > 0
            and review_growth_rate is not None
        )
        has_click = click_trend_ratio is not None and click_trend_ratio > 0

        if has_search and has_review and has_click:
            return 0.9
        elif has_search and has_review:
            return 0.6
        elif has_search and has_click:
            return 0.55
        elif has_search:
            return 0.35
        else:
            return 0.1

    # ------------------------------------------------------------------
    # 수요 추정
    # ------------------------------------------------------------------

    def estimate(
        self,
        keyword_search_volume: int,
        review_count: int | None = None,
        review_growth_rate: float | None = None,
        click_trend_ratio: float | None = None,
    ) -> DemandResult:
        """
        수요 점수를 추정합니다.

        가용한 지표만 사용하여 가중 평균을 계산합니다.
        누락된 지표는 가중치를 재분배합니다.

        Args:
            keyword_search_volume: 월간 키워드 검색량
            review_count: 현재 리뷰 수 (선택)
            review_growth_rate: 리뷰 증가율 (선택, 예: 0.5 = 50% 증가)
            click_trend_ratio: 클릭 추이 비율 (선택, 0~1)

        Returns:
            DemandResult: 수요 점수, 신뢰도, 구성 요소 상세

        Raises:
            ScoreCalculationError: 수요 추정 중 오류 발생 시

        Examples:
            >>> estimator = DemandEstimator()
            >>> result = estimator.estimate(
            ...     keyword_search_volume=50000,
            ...     review_count=150,
            ...     review_growth_rate=0.5,
            ...     click_trend_ratio=0.7,
            ... )
            >>> result.get_demand_level()
            'MEDIUM'
        """
        try:
            # 검색량 정규화 (항상 사용)
            search_score = self._normalize_search_volume(keyword_search_volume)

            # 리뷰 증가율 정규화
            has_review = (
                review_growth_rate is not None and review_count is not None
            )
            review_score = (
                self._normalize_review_growth(review_growth_rate)
                if has_review
                else None
            )

            # 클릭 추이 정규화
            has_click = click_trend_ratio is not None
            click_score = (
                self._normalize_click_trend(click_trend_ratio)
                if has_click
                else None
            )

            # 가중치 재분배: 누락된 지표의 가중치를 있는 지표에 비례 분배
            active_weights: dict[str, float] = {"search": self.search_weight}
            scores: dict[str, float] = {"search": search_score}

            if review_score is not None:
                active_weights["review"] = self.review_weight
                scores["review"] = review_score
            if click_score is not None:
                active_weights["click"] = self.click_weight
                scores["click"] = click_score

            total_active_weight = sum(active_weights.values())

            if total_active_weight == 0:
                demand_score = 0.0
            else:
                demand_score = sum(
                    scores[k] * (active_weights[k] / total_active_weight)
                    for k in scores
                )

            demand_score = round(_clamp(demand_score), 4)

            # 신뢰도
            confidence = self._compute_confidence(
                keyword_search_volume,
                review_count,
                review_growth_rate,
                click_trend_ratio,
            )

            # 구성 요소 상세
            components: dict[str, float] = {
                "search_volume_score": round(search_score, 4),
                "search_volume_raw": float(keyword_search_volume),
                "review_growth_score": round(review_score, 4) if review_score is not None else 0.0,
                "review_growth_rate_raw": float(review_growth_rate) if review_growth_rate is not None else 0.0,
                "review_count": float(review_count) if review_count is not None else 0.0,
                "click_trend_score": round(click_score, 4) if click_score is not None else 0.0,
                "click_trend_ratio_raw": float(click_trend_ratio) if click_trend_ratio is not None else 0.0,
            }

            logger.debug(
                "demand_score_estimated",
                score=demand_score,
                confidence=confidence,
                level=DemandResult(
                    score=demand_score, confidence=confidence, components=components
                ).get_demand_level(),
            )

            return DemandResult(
                score=demand_score,
                confidence=confidence,
                components=components,
            )

        except Exception as exc:
            logger.error(
                "demand_estimation_failed",
                search_volume=keyword_search_volume,
                error=str(exc),
            )
            raise ScoreCalculationError(
                message=f"수요 추정 실패: {exc}",
                metric="demand_score",
                original_error=exc,
            ) from exc

    # ------------------------------------------------------------------
    # 편의 메서드
    # ------------------------------------------------------------------

    def estimate_from_search_only(
        self,
        keyword_search_volume: int,
    ) -> DemandResult:
        """
        검색량만으로 수요를 추정합니다.

        리뷰나 클릭 데이터가 없는 초기 단계에서 사용합니다.

        Args:
            keyword_search_volume: 월간 키워드 검색량

        Returns:
            DemandResult: 수요 추정 결과 (낮은 신뢰도)
        """
        return self.estimate(keyword_search_volume=keyword_search_volume)

    def estimate_monthly_sales(
        self,
        demand_score: float,
        avg_conversion_rate: float = 0.02,
        market_share: float = 0.10,
    ) -> int:
        """
        수요 점수를 기반으로 월 예상 판매량을 추정합니다.

        간단한 비례 모델을 사용합니다.
        base_sales = demand_score * 10,000 (잠재 조회수)
        estimated = base_sales * conversion * market_share

        Args:
            demand_score: 수요 점수 (0~1)
            avg_conversion_rate: 평균 전환율 (기본값: 2%)
            market_share: 예상 시장 점유율 (기본값: 10%)

        Returns:
            int: 월 예상 판매량

        Examples:
            >>> est = DemandEstimator()
            >>> est.estimate_monthly_sales(0.7)
            14
        """
        base_sales = demand_score * 10_000
        return max(0, int(base_sales * avg_conversion_rate * market_share))
