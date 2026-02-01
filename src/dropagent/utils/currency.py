"""
환율 변환 유틸리티 모듈

중국 위안화(CNY), 미국 달러(USD)를 한국 원화(KRW)로 변환하는 기능을 제공합니다.
"""

from decimal import ROUND_HALF_UP, Decimal


def convert_cny_to_krw(
    amount: Decimal | float | int,
    exchange_rate: Decimal | float
) -> Decimal:
    """
    중국 위안화(CNY)를 한국 원화(KRW)로 변환합니다.

    Args:
        amount: 위안화 금액
        exchange_rate: CNY->KRW 환율 (예: 190.5)

    Returns:
        Decimal: 원화 금액 (소수점 2자리 반올림)

    Examples:
        >>> convert_cny_to_krw(100, 190.5)
        Decimal('19050.00')
    """
    amount_decimal = Decimal(str(amount))
    rate_decimal = Decimal(str(exchange_rate))

    result = amount_decimal * rate_decimal
    return result.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def convert_usd_to_krw(
    amount: Decimal | float | int,
    exchange_rate: Decimal | float
) -> Decimal:
    """
    미국 달러(USD)를 한국 원화(KRW)로 변환합니다.

    Args:
        amount: 달러 금액
        exchange_rate: USD->KRW 환율 (예: 1320.5)

    Returns:
        Decimal: 원화 금액 (소수점 2자리 반올림)

    Examples:
        >>> convert_usd_to_krw(100, 1320.5)
        Decimal('132050.00')
    """
    amount_decimal = Decimal(str(amount))
    rate_decimal = Decimal(str(exchange_rate))

    result = amount_decimal * rate_decimal
    return result.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def apply_exchange_buffer(
    amount: Decimal | float | int,
    buffer_rate: float = 0.05
) -> Decimal:
    """
    환율 변동 리스크를 위한 버퍼를 적용합니다.

    PRD 기준: 환율 마진 5% 적용

    Args:
        amount: 원화 금액
        buffer_rate: 버퍼 비율 (기본값: 0.05 = 5%)

    Returns:
        Decimal: 버퍼가 적용된 금액 (소수점 2자리 반올림)

    Examples:
        >>> apply_exchange_buffer(10000, 0.05)
        Decimal('10500.00')
    """
    amount_decimal = Decimal(str(amount))
    buffer_decimal = Decimal(str(1 + buffer_rate))

    result = amount_decimal * buffer_decimal
    return result.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def convert_with_buffer(
    amount: Decimal | float | int,
    exchange_rate: Decimal | float,
    currency: str = "CNY",
    buffer_rate: float = 0.05
) -> Decimal:
    """
    환율 변환 후 버퍼를 적용합니다.

    Args:
        amount: 외화 금액
        exchange_rate: 환율
        currency: 통화 코드 ("CNY" 또는 "USD")
        buffer_rate: 버퍼 비율 (기본값: 0.05 = 5%)

    Returns:
        Decimal: 버퍼가 적용된 원화 금액

    Raises:
        ValueError: 지원하지 않는 통화 코드

    Examples:
        >>> convert_with_buffer(100, 190.5, "CNY", 0.05)
        Decimal('20002.50')
    """
    if currency.upper() == "CNY":
        converted = convert_cny_to_krw(amount, exchange_rate)
    elif currency.upper() == "USD":
        converted = convert_usd_to_krw(amount, exchange_rate)
    else:
        raise ValueError(f"Unsupported currency: {currency}. Use 'CNY' or 'USD'.")

    return apply_exchange_buffer(converted, buffer_rate)
