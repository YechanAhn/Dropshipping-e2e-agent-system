"""
운영 비용 스코어링 엔진

드롭쉬핑 상품의 운영 복잡도와 비용을 평가합니다.

PRD 운영비용 요소:
    | 요소                | 벌점              | 비고                 |
    |---------------------|-------------------|--------------------- |
    | 옵션 수             | 5+: 0.6, 10+: 0.9 | 등록 복잡도         |
    | 상세 페이지 난이도  | 사이즈차트: 0.5   | LLM 비용 증가       |
    | 예상 CS량           | 카테고리 기반      | 의류: 높음           |
    | 반품률              | 카테고리 평균      | 의류 15%+: 패널티   |

총 운영비용 점수: 각 요소의 가중 평균 (0~1)
"""

from dataclasses import dataclass

from dropagent.utils.exceptions import ScoreCalculationError
from dropagent.utils.logging import get_logger

logger = get_logger(__name__)


# =====================================================================
# 카테고리별 예상 CS 발생률 (0~1)
# =====================================================================
CATEGORY_CS_RATES: dict[str, float] = {
    # 높은 CS 발생률
    "패션의류": 0.8,
    "패션잡화": 0.7,
    "주얼리/액세서리": 0.6,
    "화장품/미용": 0.7,

    # 중간 CS 발생률
    "디지털/가전": 0.6,
    "컴퓨터/주변기기": 0.6,
    "완구/취미": 0.5,
    "스포츠/레저": 0.5,
    "카메라/캠코더": 0.55,

    # 낮은 CS 발생률
    "생활용품": 0.3,
    "주방용품": 0.3,
    "인테리어소품": 0.35,
    "반려동물용품": 0.35,
    "도서": 0.2,
    "문구/오피스": 0.2,
    "식품": 0.4,
}

# =====================================================================
# 카테고리별 예상 반품률 (0~1 정규화)
# =====================================================================
CATEGORY_RETURN_RATES: dict[str, float] = {
    # 높은 반품률 (15% 이상)
    "패션의류": 0.8,
    "패션잡화": 0.7,
    "주얼리/액세서리": 0.6,
    "화장품/미용": 0.6,

    # 중간 반품률 (5-15%)
    "디지털/가전": 0.5,
    "컴퓨터/주변기기": 0.5,
    "완구/취미": 0.4,
    "생활용품": 0.4,
    "카메라/캠코더": 0.45,
    "스포츠/레저": 0.4,

    # 낮은 반품률 (5% 미만)
    "주방용품": 0.2,
    "인테리어소품": 0.3,
    "반려동물용품": 0.25,
    "도서": 0.1,
    "문구/오피스": 0.1,
    "식품": 0.1,
}

DEFAULT_CS_RATE = 0.4
DEFAULT_RETURN_RATE = 0.4

# 운영비용 요소별 기본 가중치
DEFAULT_OPS_WEIGHTS: dict[str, float] = {
    "option_complexity": 0.25,
    "page_difficulty": 0.20,
    "cs_volume": 0.30,
    "return_rate": 0.25,
}


@dataclass(frozen=True)
class OpsCostResult:
    """운영 비용 평가 결과"""

    score: float  # 총 운영 비용 점수 (0~1)
    factors: dict[str, float]  # 개별 운영 비용 요소 점수
    warnings: list[str]  # 경고 메시지 목록

    def get_ops_level(self) -> str:
        """
        운영 복잡도 수준을 문자열로 반환합니다.

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


class OpsCostScorer:
    """
    운영 비용 스코어 계산기

    옵션 복잡도, 상세 페이지 난이도, 예상 CS량, 반품률 등을
    종합 평가하여 0~1 범위의 운영비용 점수를 산출합니다.
    """

    def __init__(
        self,
        cs_rates: dict[str, float] | None = None,
        return_rates: dict[str, float] | None = None,
        weights: dict[str, float] | None = None,
    ) -> None:
        """
        Args:
            cs_rates: 카테고리별 CS 발생률 딕셔너리
            return_rates: 카테고리별 반품률 딕셔너리
            weights: 운영비용 요소별 가중치
        """
        self.cs_rates = cs_rates or dict(CATEGORY_CS_RATES)
        self.return_rates = return_rates or dict(CATEGORY_RETURN_RATES)
        self.weights = weights or dict(DEFAULT_OPS_WEIGHTS)
        logger.info("ops_cost_scorer_initialized", weights=self.weights)

    # ------------------------------------------------------------------
    # 개별 요소 계산
    # ------------------------------------------------------------------

    @staticmethod
    def _option_complexity(option_count: int) -> float:
        """
        상품 옵션 수에 따른 등록/관리 복잡도를 계산합니다.

        Args:
            option_count: 옵션 개수

        Returns:
            float: 옵션 복잡도 점수 (0~1)
                10개 이상 -> 0.9
                5~9개    -> 0.6
                3~4개    -> 0.3
                3개 미만 -> 0.1
        """
        if option_count >= 10:
            return 0.9
        elif option_count >= 5:
            return 0.6
        elif option_count >= 3:
            return 0.3
        else:
            return 0.1

    @staticmethod
    def _page_difficulty(has_size_chart: bool) -> float:
        """
        상세 페이지 제작 난이도를 계산합니다.

        사이즈차트가 필요한 경우(의류 등) LLM 비용이 증가하고
        상세 페이지 제작 시간이 늘어납니다.

        Args:
            has_size_chart: 사이즈차트 필요 여부

        Returns:
            float: 페이지 난이도 점수 (0~1)
        """
        if has_size_chart:
            return 0.5
        return 0.1

    def _cs_volume_estimate(self, category: str) -> float:
        """
        카테고리에 따른 예상 CS 발생률을 반환합니다.

        Args:
            category: 상품 카테고리

        Returns:
            float: CS 발생률 예측 점수 (0~1)
        """
        return self.cs_rates.get(category, DEFAULT_CS_RATE)

    def _return_rate_score(
        self,
        category: str,
        estimated_return_rate: float | None = None,
    ) -> float:
        """
        반품률 위험도를 산출합니다.

        직접 추정 반품률이 주어지면 그 값을 정규화(0~1)하여 사용하고,
        그렇지 않으면 카테고리 기반 기본값을 사용합니다.

        Args:
            category: 상품 카테고리
            estimated_return_rate: 직접 추정 반품률 (0.0~1.0)

        Returns:
            float: 반품률 위험도 (0~1)
        """
        if estimated_return_rate is not None:
            # 직접 입력된 반품률 사용 (0~1 클리핑)
            return max(0.0, min(1.0, estimated_return_rate))
        return self.return_rates.get(category, DEFAULT_RETURN_RATE)

    # ------------------------------------------------------------------
    # 경고 메시지 생성
    # ------------------------------------------------------------------

    @staticmethod
    def _build_warnings(
        option_count: int,
        page_diff: float,
        cs_est: float,
        return_risk: float,
        category: str,
    ) -> list[str]:
        """운영 비용 수준에 따라 경고 메시지를 생성합니다."""
        warnings: list[str] = []

        if option_count >= 10:
            warnings.append(
                f"옵션 수가 {option_count}개로 등록 및 재고 관리가 매우 복잡합니다."
            )
        elif option_count >= 5:
            warnings.append(
                f"옵션 수가 {option_count}개로 등록 복잡도가 높습니다."
            )

        if page_diff >= 0.5:
            warnings.append(
                "사이즈차트가 필요하여 상세 페이지 제작 비용이 증가합니다."
            )

        if cs_est >= 0.7:
            warnings.append(
                f"카테고리 '{category}'는 CS 발생률이 매우 높습니다 ({cs_est:.2f}). "
                "CS 대응 인력을 확보하세요."
            )

        if return_risk >= 0.7:
            warnings.append(
                f"반품률이 매우 높을 것으로 예상됩니다 ({return_risk:.2f}). "
                "반품 비용을 마진에 반영하세요."
            )
        elif return_risk >= 0.5:
            warnings.append(
                f"반품률이 다소 높습니다 ({return_risk:.2f}). "
                "상세 설명을 강화하여 반품을 줄이세요."
            )

        return warnings

    # ------------------------------------------------------------------
    # 통합 계산
    # ------------------------------------------------------------------

    def calculate(
        self,
        option_count: int,
        has_size_chart: bool,
        category: str,
        estimated_return_rate: float | None = None,
    ) -> OpsCostResult:
        """
        전체 운영 비용 점수를 계산합니다.

        4가지 비용 요소(옵션 복잡도, 페이지 난이도, CS량, 반품률)의
        가중 평균을 산출합니다.

        Args:
            option_count: 옵션 개수
            has_size_chart: 사이즈차트 필요 여부
            category: 상품 카테고리 (네이버 기준)
            estimated_return_rate: 추정 반품률 (0.0~1.0, 선택)

        Returns:
            OpsCostResult: 운영비용 점수, 요소별 상세, 경고 메시지

        Raises:
            ScoreCalculationError: 운영비용 계산 중 오류 발생 시

        Examples:
            >>> scorer = OpsCostScorer()
            >>> result = scorer.calculate(
            ...     option_count=8,
            ...     has_size_chart=True,
            ...     category="패션의류",
            ... )
            >>> result.get_ops_level()
            'HIGH'
        """
        try:
            opt_score = self._option_complexity(option_count)
            page_score = self._page_difficulty(has_size_chart)
            cs_score = self._cs_volume_estimate(category)
            return_score = self._return_rate_score(category, estimated_return_rate)

            factors: dict[str, float] = {
                "option_complexity": round(opt_score, 4),
                "page_difficulty": round(page_score, 4),
                "cs_volume": round(cs_score, 4),
                "return_rate": round(return_score, 4),
            }

            # 가중 평균
            w = self.weights
            total_weight = sum(w.values())
            if total_weight == 0:
                total_ops = 0.0
            else:
                total_ops = (
                    opt_score * w.get("option_complexity", 0.0)
                    + page_score * w.get("page_difficulty", 0.0)
                    + cs_score * w.get("cs_volume", 0.0)
                    + return_score * w.get("return_rate", 0.0)
                ) / total_weight

            total_ops = round(min(1.0, max(0.0, total_ops)), 4)

            warnings = self._build_warnings(
                option_count, page_score, cs_score, return_score, category
            )

            logger.debug(
                "ops_cost_calculated",
                category=category,
                score=total_ops,
                level=OpsCostResult(
                    score=total_ops, factors=factors, warnings=warnings
                ).get_ops_level(),
            )

            return OpsCostResult(
                score=total_ops,
                factors=factors,
                warnings=warnings,
            )

        except Exception as exc:
            logger.error(
                "ops_cost_calculation_failed",
                category=category,
                error=str(exc),
            )
            raise ScoreCalculationError(
                message=f"운영비용 스코어 계산 실패: {exc}",
                metric="ops_cost_score",
                original_error=exc,
            ) from exc

    # ------------------------------------------------------------------
    # 커스텀 카테고리 등록
    # ------------------------------------------------------------------

    def add_custom_category_rates(
        self,
        category: str,
        cs_rate: float | None = None,
        return_rate: float | None = None,
    ) -> None:
        """
        커스텀 카테고리의 CS/반품률을 추가합니다.

        Args:
            category: 카테고리명
            cs_rate: CS 발생률 (0~1)
            return_rate: 반품률 (0~1)

        Raises:
            ValueError: 값이 0~1 범위를 벗어난 경우
        """
        if cs_rate is not None:
            if not (0.0 <= cs_rate <= 1.0):
                raise ValueError(
                    f"cs_rate는 0~1 범위여야 합니다. 입력값: {cs_rate}"
                )
            self.cs_rates[category] = cs_rate

        if return_rate is not None:
            if not (0.0 <= return_rate <= 1.0):
                raise ValueError(
                    f"return_rate는 0~1 범위여야 합니다. 입력값: {return_rate}"
                )
            self.return_rates[category] = return_rate

        logger.info(
            "custom_ops_category_added",
            category=category,
            cs_rate=cs_rate,
            return_rate=return_rate,
        )
