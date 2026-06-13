"""
가격 결정 엔진 (Optimal Pricing)

수요 우선(demand-first) 드롭쉬핑 리스팅의 최적 판매가를 결정합니다.

핵심 아이디어 (docs/RESEARCH_discovery.md §5):
    - 네이버 스마트스토어 결합 수수료는 **~6%** 다 (흔히 쓰는 10~11% 가 아님).
      2025-06 개편: 주문관리 3.63% + 판매수수료 ~2%. 기본값 ``SMARTSTORE_FEE_RATE``.
    - 한국 구매대행 셀러는 **마진율 20~30%** 와 **건당 절대이익 하한**(최소 ₩5,000 /
      목표 ₩10,000) 을 동시에 노린다. 둘 다 만족하지 못하면 환율·반품에 적자 전환.
    - 경쟁 가격대를 **언더컷** 하되 마진 하한 아래로는 절대 내려가지 않는다.
      ₩x,900 형태의 심리적(charm) 가격으로 라운딩하는 것이 한국 시장 표준.

설계 원칙:
    - 모든 함수/데이터클래스는 **순수(pure)·결정적(deterministic)** 이며 외부 I/O 가 없다.
    - 금액 계산은 ``Decimal`` 로 하고, 최종 가격은 ``int``(원) 로 반환한다.

공개 API:
    - :class:`PricingResult`
    - :func:`optimal_price`
    - :func:`charm_round`
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from dropagent.utils.logging import get_logger

logger = get_logger(__name__)

# 네이버 스마트스토어 결합 수수료율 기본값 (~6%, VAT 별도).
# 출처: docs/RESEARCH_discovery.md §5 (검증 HIGH).
SMARTSTORE_FEE_RATE: Decimal = Decimal("0.06")

# 건당 절대 순이익 하한 기본값 (원). 이하면 환율·반품 리스크에 적자 전환.
DEFAULT_MIN_PROFIT: int = 5000

# 목표 마진율 기본값 (판매가 대비 순이익 비율).
DEFAULT_TARGET_MARGIN: Decimal = Decimal("0.30")


@dataclass
class PricingResult:
    """가격 결정 결과.

    Attributes:
        recommended_price: 권장 판매가 (원, charm 라운딩 적용). 비현실적이어도
            마진 하한을 만족하는 최소 가격을 담는다(``feasible`` 로 판단할 것).
        floor_price: 마진 하한 가격 (원). 이 가격 미만이면 목표 마진/최소이익을
            만족하지 못한다.
        competitive_p25: 경쟁가 25분위수 (원). 경쟁 리스트가 비면 ``None``.
        competitive_median: 경쟁가 중앙값 (원). 경쟁 리스트가 비면 ``None``.
        expected_margin_rate: ``recommended_price`` 에서의 예상 마진율
            (판매가 대비 순이익 비율, 예: 0.30 = 30%).
        expected_profit: ``recommended_price`` 에서의 예상 순이익 (원).
        feasible: 경쟁가를 언더컷하면서도 마진 하한을 지킬 수 있으면 ``True``.
        reason: 결정 근거 / 사유 (특히 ``feasible`` 가 ``False`` 일 때).
    """

    recommended_price: int
    floor_price: int
    competitive_p25: int | None
    competitive_median: int | None
    expected_margin_rate: float
    expected_profit: int
    feasible: bool
    reason: str


def _percentile(sorted_values: list[int], q: float) -> Decimal:
    """정렬된 정수 리스트의 분위수를 선형 보간으로 계산한다.

    numpy 의 기본('linear') 방식과 동일하다. 빈 리스트는 호출 전에 걸러야 한다.

    Args:
        sorted_values: 오름차순 정렬된 값 리스트 (비어 있지 않아야 함).
        q: 0.0~1.0 사이의 분위수.

    Returns:
        Decimal: 보간된 분위수 값.
    """
    n = len(sorted_values)
    if n == 1:
        return Decimal(sorted_values[0])

    # 0-기반 인덱스 위치 (선형 보간)
    pos = Decimal(str(q)) * Decimal(n - 1)
    lower_idx = int(pos)  # floor
    upper_idx = min(lower_idx + 1, n - 1)
    frac = pos - Decimal(lower_idx)

    lower_val = Decimal(sorted_values[lower_idx])
    upper_val = Decimal(sorted_values[upper_idx])
    return lower_val + (upper_val - lower_val) * frac


def charm_round(price: int, round_to: int = 100, charm: bool = True) -> int:
    """심리적(charm) 가격 라운딩.

    동작 (결정적):
        1. ``price`` 를 ``round_to`` 단위로 **올림**(ceil) 한다. 셀러는 마진 하한을
           깨지 않도록 항상 위로 라운딩한다.
        2. ``charm`` 이 참이고 그 결과가 1,000 이상이면, 마지막 3자리를 ``900`` 으로
           만든다(즉 ₩x,900 형태). 라운딩된 값의 천 단위를 기준으로 ``...900`` 을
           고르되, 그 값이 라운딩 결과보다 작으면 한 천 단위 올린다.

    Examples:
        >>> charm_round(10250)        # ceil→10300 → 10900
        10900
        >>> charm_round(10900)        # 이미 ...900
        10900
        >>> charm_round(11000)        # ceil→11000 → 11900 (11000 의 ...900 은 10900<11000)
        11900
        >>> charm_round(10250, charm=False)
        10300
        >>> charm_round(950)          # ceil→1000 → 1900 (1000 의 ...900=900<1000)
        1900
        >>> charm_round(8001, round_to=1000)   # ceil→9000 → 9900
        9900

    Args:
        price: 라운딩할 가격 (원). 음수/0 은 그대로(혹은 round_to) 반환.
        round_to: 올림 단위 (원). 1 이하이면 올림은 생략.
        charm: ₩x,900 charm 라운딩 적용 여부.

    Returns:
        int: 라운딩된 가격.
    """
    if price <= 0:
        return 0

    # 1) round_to 단위로 올림
    if round_to > 1:
        rounded = ((price + round_to - 1) // round_to) * round_to
    else:
        rounded = price

    if not charm or rounded < 1000:
        return rounded

    # 2) ₩x,900 charm: 현재 천 단위에 900 을 붙이고, 부족하면 한 천 단위 올림
    thousands = rounded // 1000
    candidate = thousands * 1000 + 900
    if candidate < rounded:
        candidate += 1000
    return candidate


def _net_profit(price: Decimal, landed_cost: Decimal, fee_rate: Decimal) -> Decimal:
    """판매가에서의 순이익: ``price * (1 - fee_rate) - landed_cost``."""
    return price * (Decimal("1") - fee_rate) - landed_cost


def _margin_floor_price(
    landed_cost: Decimal,
    fee_rate: Decimal,
    target_margin: Decimal,
    min_profit: int,
) -> Decimal | None:
    """마진 하한 가격 P_floor 를 닫힌 형태로 계산한다.

    두 제약을 동시에 만족하는 최소 가격 P:
        (a) 목표 마진율:   P*(1-fee) - landed >= target_margin * P
            => P >= landed / (1 - fee - target_margin)
        (b) 최소 절대이익: P*(1-fee) - landed >= min_profit
            => P >= (landed + min_profit) / (1 - fee)

    P_floor = max(a, b).

    Args:
        landed_cost: 알리 랜딩 원가 (원, 수수료 제외 모든 비용 포함).
        fee_rate: 스마트스토어 수수료 비율.
        target_margin: 목표 마진율 (판매가 대비).
        min_profit: 최소 절대 순이익 (원).

    Returns:
        Decimal | None: P_floor. ``1 - fee - target_margin <= 0`` 이면(목표 마진을
        수수료 구조상 달성 불가) 제약 (a) 가 무한대가 되어 ``None`` 을 반환한다.
    """
    one = Decimal("1")
    margin_denominator = one - fee_rate - target_margin
    if margin_denominator <= 0:
        # 목표 마진 + 수수료가 100% 이상 → 어떤 가격으로도 목표 마진 달성 불가.
        return None

    floor_margin = landed_cost / margin_denominator
    floor_min_profit = (landed_cost + Decimal(min_profit)) / (one - fee_rate)
    return max(floor_margin, floor_min_profit)


def optimal_price(
    landed_cost: Decimal,
    competitor_prices: list[int],
    *,
    target_margin: Decimal = DEFAULT_TARGET_MARGIN,
    fee_rate: Decimal = SMARTSTORE_FEE_RATE,
    min_profit: int = DEFAULT_MIN_PROFIT,
    undercut: Decimal = Decimal("0.01"),
    round_to: int = 100,
    charm: bool = True,
) -> PricingResult:
    """수요 우선 리스팅의 최적 판매가를 결정한다.

    절차:
        1. 경쟁가에서 25분위수(p25)·중앙값(median)을 계산한다(빈 리스트 처리).
        2. 마진 하한 가격 ``P_floor`` 를 닫힌 형태로 구한다
           (:func:`_margin_floor_price`).
        3. 목표 가격 = p25 를 살짝 언더컷 ``p25 * (1 - undercut)``.
        4. 최종(raw) = ``max(목표, P_floor)`` → charm 라운딩 적용.
        5. 실현 가능성(feasible) 판단:
            - 경쟁가가 없으면 ``False`` (수요/경쟁 신호 부재 → 가격대 미상).
            - 목표 마진이 수수료 구조상 불가능하면 ``False``.
            - ``p25 < P_floor`` 면 ``False`` (경쟁가를 따라가면 마진을 못 지킴).
        6. ``expected_margin_rate`` / ``expected_profit`` 은 **권장가** 기준으로 계산.

    Args:
        landed_cost: 알리 랜딩 원가 (원). 상품가+배송+환율버퍼 등 수수료 제외 총원가.
        competitor_prices: 네이버 경쟁 판매가 리스트 (원, 정수).
        target_margin: 목표 마진율 (판매가 대비 순이익 비율). 기본 0.30.
        fee_rate: 스마트스토어 수수료 비율. 기본 :data:`SMARTSTORE_FEE_RATE`.
        min_profit: 건당 최소 절대 순이익 (원). 기본 :data:`DEFAULT_MIN_PROFIT`.
        undercut: 경쟁 p25 대비 언더컷 비율. 기본 0.01 (1%).
        round_to: charm 라운딩 올림 단위. 기본 100.
        charm: ₩x,900 charm 라운딩 적용 여부. 기본 True.

    Returns:
        PricingResult: 권장가·하한가·경쟁 통계·예상 마진/이익·실현가능성·사유.
    """
    landed = Decimal(landed_cost)

    # --- 1) 경쟁 통계 ---
    has_competition = bool(competitor_prices)
    p25_dec: Decimal | None = None
    median_dec: Decimal | None = None
    competitive_p25: int | None = None
    competitive_median: int | None = None
    if has_competition:
        ordered = sorted(int(p) for p in competitor_prices)
        p25_dec = _percentile(ordered, 0.25)
        median_dec = _percentile(ordered, 0.50)
        competitive_p25 = int(p25_dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        competitive_median = int(median_dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    # --- 2) 마진 하한 가격 ---
    floor_dec = _margin_floor_price(landed, fee_rate, target_margin, min_profit)
    margin_achievable = floor_dec is not None
    if floor_dec is not None:
        # 하한은 위로 올림(라운딩 단위 무시, 안전측). int 로 보관.
        floor_price = int(floor_dec.quantize(Decimal("1"), rounding=ROUND_CEILING))
    else:
        floor_price = 0

    # --- 3) 목표 가격(언더컷) + 4) 최종 raw 가격 ---
    if margin_achievable:
        if has_competition and p25_dec is not None:
            target_dec = p25_dec * (Decimal("1") - undercut)
            raw_dec = max(target_dec, floor_dec)  # type: ignore[arg-type]
        else:
            # 경쟁 정보가 없으면 마진 하한을 권장가로 제시(참고용, feasible=False).
            raw_dec = floor_dec  # type: ignore[assignment]
        raw_price = int(raw_dec.quantize(Decimal("1"), rounding=ROUND_CEILING))
        recommended_price = charm_round(raw_price, round_to=round_to, charm=charm)
    else:
        # 목표 마진 자체가 불가능 → 권장가 없음(0).
        recommended_price = 0

    # --- 5) feasibility 판단 + 사유 ---
    if not margin_achievable:
        feasible = False
        reason = (
            f"목표 마진 {target_margin} 은 수수료율 {fee_rate} 구조상 달성 불가 "
            f"(1 - fee - margin <= 0)."
        )
    elif not has_competition:
        feasible = False
        reason = (
            "경쟁가 데이터가 없어 가격대를 알 수 없음. 마진 하한 가격을 참고용으로 제시."
        )
    elif p25_dec is not None and p25_dec < floor_dec:  # type: ignore[operator]
        feasible = False
        reason = (
            f"경쟁 p25({competitive_p25:,})가 마진 하한({floor_price:,}) 미만 → "
            f"경쟁가를 따라가면 목표 마진/최소이익을 지킬 수 없음."
        )
    else:
        feasible = True
        reason = (
            f"경쟁 p25({competitive_p25:,})를 {undercut} 언더컷, "
            f"마진 하한({floor_price:,}) 이상에서 권장가 결정."
        )

    # --- 6) 권장가 기준 예상 마진/이익 ---
    if recommended_price > 0:
        rec_dec = Decimal(recommended_price)
        profit_dec = _net_profit(rec_dec, landed, fee_rate)
        expected_profit = int(profit_dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        expected_margin_rate = float(
            (profit_dec / rec_dec).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        )
    else:
        expected_profit = 0
        expected_margin_rate = 0.0

    logger.debug(
        "optimal_price_computed",
        landed_cost=str(landed),
        recommended_price=recommended_price,
        floor_price=floor_price,
        competitive_p25=competitive_p25,
        competitive_median=competitive_median,
        expected_margin_rate=expected_margin_rate,
        expected_profit=expected_profit,
        feasible=feasible,
    )

    return PricingResult(
        recommended_price=recommended_price,
        floor_price=floor_price,
        competitive_p25=competitive_p25,
        competitive_median=competitive_median,
        expected_margin_rate=expected_margin_rate,
        expected_profit=expected_profit,
        feasible=feasible,
        reason=reason,
    )
