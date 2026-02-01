"""
마진율 계산 엔진

PRD에 정의된 공식에 따라 드롭쉬핑 상품의 마진율을 계산합니다.

공식:
    마진율 = (네이버 판매 예상가 - 총 원가) / 네이버 판매 예상가 × 100

    총 원가 = 알리 상품가 + 알리 배송비 + 환율 마진(5%)
             + 네이버 수수료(카테고리별 5.5~11%)
             + CS 리스크(3%) + 환불/반품(2%)
"""

import statistics
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

# 카테고리별 네이버 커머스 수수료율 (%)
NAVER_COMMISSION_RATES: dict[str, Decimal] = {
    # 패션/잡화
    "패션의류": Decimal("7.0"),
    "패션잡화": Decimal("7.0"),
    "화장품/미용": Decimal("8.0"),
    "주얼리/액세서리": Decimal("7.5"),

    # 디지털/가전
    "디지털/가전": Decimal("5.5"),
    "컴퓨터/주변기기": Decimal("5.5"),
    "카메라/캠코더": Decimal("6.0"),

    # 스포츠/레저
    "스포츠/레저": Decimal("8.0"),
    "자동차용품": Decimal("7.0"),

    # 생활/건강
    "생활/건강": Decimal("9.0"),
    "식품": Decimal("11.0"),
    "출산/육아": Decimal("8.5"),
    "반려동물용품": Decimal("8.0"),

    # 가구/인테리어
    "가구/인테리어": Decimal("9.0"),
    "주방용품": Decimal("8.5"),

    # 도서/취미
    "도서": Decimal("10.0"),
    "문구/오피스": Decimal("8.0"),
    "취미/게임": Decimal("7.5"),

    # 기타
    "기타": Decimal("8.0"),
}

# 기본 수수료율 (카테고리가 매칭되지 않을 때)
DEFAULT_COMMISSION_RATE = Decimal("8.0")

# 고정 비용 비율
EXCHANGE_BUFFER_RATE = Decimal("0.05")  # 환율 마진 5%
CS_RISK_RATE = Decimal("0.03")  # CS 리스크 3%
REFUND_RETURN_RATE = Decimal("0.02")  # 환불/반품 2%


@dataclass
class CostBreakdown:
    """원가 구성 항목별 상세 내역"""

    ali_price: Decimal  # 알리 상품가 (원화 환산)
    ali_shipping: Decimal  # 알리 배송비 (원화 환산)
    exchange_margin: Decimal  # 환율 마진 (5%)
    naver_commission: Decimal  # 네이버 수수료 (카테고리별)
    cs_risk: Decimal  # CS 리스크 (3%)
    refund_return: Decimal  # 환불/반품 (2%)

    def total(self) -> Decimal:
        """총 원가를 계산합니다."""
        return (
            self.ali_price +
            self.ali_shipping +
            self.exchange_margin +
            self.naver_commission +
            self.cs_risk +
            self.refund_return
        )


@dataclass
class MarginResult:
    """마진 계산 결과"""

    total_cost: Decimal  # 총 원가
    margin_rate: Decimal  # 마진율 (%)
    naver_estimated_price: Decimal  # 네이버 판매 예상가
    breakdown: CostBreakdown  # 원가 구성 상세

    def expected_profit(self) -> Decimal:
        """예상 수익을 계산합니다."""
        return self.naver_estimated_price - self.total_cost


class MarginCalculator:
    """마진율 계산기"""

    def __init__(self, commission_rates: dict[str, Decimal] = None):
        """
        Args:
            commission_rates: 카테고리별 수수료율 딕셔너리 (선택사항)
        """
        self.commission_rates = commission_rates or NAVER_COMMISSION_RATES

    def get_commission_rate(self, category: str) -> Decimal:
        """
        카테고리에 해당하는 네이버 수수료율을 반환합니다.

        Args:
            category: 상품 카테고리명

        Returns:
            Decimal: 수수료율 (소수, 예: 0.08 = 8%)
        """
        rate_percent = self.commission_rates.get(category, DEFAULT_COMMISSION_RATE)
        return rate_percent / Decimal("100")

    def calculate_total_cost(
        self,
        ali_price: Decimal | float | int,
        shipping: Decimal | float | int,
        exchange_rate: Decimal | float,
        category: str,
        naver_estimated_price: Decimal | float | int = None
    ) -> CostBreakdown:
        """
        총 원가를 계산하고 구성 항목별 상세 내역을 반환합니다.

        Args:
            ali_price: 알리익스프레스 상품가 (CNY)
            shipping: 알리익스프레스 배송비 (CNY)
            exchange_rate: CNY->KRW 환율
            category: 상품 카테고리
            naver_estimated_price: 네이버 판매 예상가 (원화, 비율 계산용)

        Returns:
            CostBreakdown: 원가 구성 상세 내역
        """
        # CNY -> KRW 변환
        ali_price_krw = Decimal(str(ali_price)) * Decimal(str(exchange_rate))
        ali_shipping_krw = Decimal(str(shipping)) * Decimal(str(exchange_rate))

        # 환율 마진 (알리 상품가 + 배송비 기준 5%)
        base_cost = ali_price_krw + ali_shipping_krw
        exchange_margin = base_cost * EXCHANGE_BUFFER_RATE

        # 네이버 수수료 (판매가 기준)
        if naver_estimated_price is not None:
            naver_price = Decimal(str(naver_estimated_price))
            commission_rate = self.get_commission_rate(category)
            naver_commission = naver_price * commission_rate
        else:
            # 판매가가 없으면 원가 기준으로 추정
            naver_commission = base_cost * Decimal("0.08")

        # CS 리스크 (판매가 기준)
        if naver_estimated_price is not None:
            cs_risk = naver_price * CS_RISK_RATE
            refund_return = naver_price * REFUND_RETURN_RATE
        else:
            cs_risk = base_cost * CS_RISK_RATE
            refund_return = base_cost * REFUND_RETURN_RATE

        return CostBreakdown(
            ali_price=ali_price_krw.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
            ali_shipping=ali_shipping_krw.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
            exchange_margin=exchange_margin.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
            naver_commission=naver_commission.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
            cs_risk=cs_risk.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
            refund_return=refund_return.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
        )

    def calculate_margin_rate(
        self,
        naver_price: Decimal | float | int,
        total_cost: Decimal | float | int
    ) -> Decimal:
        """
        마진율을 계산합니다.

        Args:
            naver_price: 네이버 판매 예상가
            total_cost: 총 원가

        Returns:
            Decimal: 마진율 (%, 소수점 2자리)

        Examples:
            >>> calc = MarginCalculator()
            >>> calc.calculate_margin_rate(10000, 7000)
            Decimal('30.00')
        """
        naver_price_decimal = Decimal(str(naver_price))
        total_cost_decimal = Decimal(str(total_cost))

        if naver_price_decimal == 0:
            return Decimal("0.00")

        margin = naver_price_decimal - total_cost_decimal
        margin_rate = (margin / naver_price_decimal) * Decimal("100")

        return margin_rate.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    def estimate_naver_price(
        self,
        prices: list[Decimal | float | int]
    ) -> Decimal:
        """
        네이버 쇼핑 경쟁사 가격의 중앙값을 기준으로 판매 예상가를 추정합니다.

        Args:
            prices: 네이버 쇼핑 경쟁사 가격 리스트

        Returns:
            Decimal: 판매 예상가 (중앙값)

        Examples:
            >>> calc = MarginCalculator()
            >>> calc.estimate_naver_price([10000, 12000, 11000, 15000, 10500])
            Decimal('11000.00')
        """
        if not prices:
            return Decimal("0.00")

        prices_decimal = [Decimal(str(p)) for p in prices]
        median_price = Decimal(str(statistics.median(prices_decimal)))

        return median_price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    def calculate(
        self,
        ali_price: Decimal | float | int,
        shipping: Decimal | float | int,
        exchange_rate: Decimal | float,
        category: str,
        naver_prices: list[Decimal | float | int] = None,
        naver_estimated_price: Decimal | float | int = None
    ) -> MarginResult:
        """
        마진율을 계산하고 결과를 반환합니다.

        Args:
            ali_price: 알리익스프레스 상품가 (CNY)
            shipping: 알리익스프레스 배송비 (CNY)
            exchange_rate: CNY->KRW 환율
            category: 상품 카테고리
            naver_prices: 네이버 쇼핑 경쟁사 가격 리스트 (선택사항)
            naver_estimated_price: 네이버 판매 예상가 (선택사항, naver_prices보다 우선)

        Returns:
            MarginResult: 마진 계산 결과

        Examples:
            >>> calc = MarginCalculator()
            >>> result = calc.calculate(
            ...     ali_price=100,
            ...     shipping=10,
            ...     exchange_rate=190,
            ...     category="패션의류",
            ...     naver_prices=[30000, 32000, 31000]
            ... )
            >>> result.margin_rate
            Decimal('35.48')
        """
        # 네이버 판매 예상가 결정
        if naver_estimated_price is not None:
            estimated_price = Decimal(str(naver_estimated_price))
        elif naver_prices:
            estimated_price = self.estimate_naver_price(naver_prices)
        else:
            raise ValueError("Either naver_prices or naver_estimated_price must be provided")

        # 원가 계산
        breakdown = self.calculate_total_cost(
            ali_price=ali_price,
            shipping=shipping,
            exchange_rate=exchange_rate,
            category=category,
            naver_estimated_price=estimated_price
        )

        total_cost = breakdown.total()

        # 마진율 계산
        margin_rate = self.calculate_margin_rate(estimated_price, total_cost)

        return MarginResult(
            total_cost=total_cost.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
            margin_rate=margin_rate,
            naver_estimated_price=estimated_price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
            breakdown=breakdown
        )
