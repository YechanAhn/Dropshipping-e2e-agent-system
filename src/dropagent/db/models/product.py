"""
Product Model
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DECIMAL, BigInteger, Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from . import Base, TimestampMixin


class Product(Base, TimestampMixin):
    """Product table for storing AliExpress and Naver product information"""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Product identifiers
    ali_product_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    naver_product_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)

    # Product information
    product_name_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_name_ko: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Categories
    category_ali: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category_naver: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Pricing
    price_ali: Mapped[Decimal | None] = mapped_column(DECIMAL(10, 2), nullable=True)
    price_naver: Mapped[Decimal | None] = mapped_column(DECIMAL(10, 2), nullable=True)

    # 최저가 노출 추적 (초기 사업자는 최저가를 맞춰야 노출 가능)
    # naver_catalog_lowest  = 가격비교 대표(catalog) 최저가 = 배지 가격
    # naver_price_min_market = 검색결과 전체 최저가 (단독 포함 시장 바닥가)
    # is_price_lowest       = 현재 우리가 최저가(배지) 보유 중인지
    # price_floor           = 마진 하한 가격 (재가격책정 시 원가 재계산 회피용 캐시)
    # pricing_strategy      = "catalog_match" | "standalone"
    # last_repriced_at      = 마지막 자동 재가격책정 시각
    naver_catalog_lowest: Mapped[Decimal | None] = mapped_column(DECIMAL(10, 2), nullable=True)
    naver_price_min_market: Mapped[Decimal | None] = mapped_column(DECIMAL(10, 2), nullable=True)
    is_price_lowest: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    price_floor: Mapped[Decimal | None] = mapped_column(DECIMAL(10, 2), nullable=True)
    pricing_strategy: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_repriced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Scores and metrics
    margin_rate: Mapped[Decimal | None] = mapped_column(DECIMAL(5, 2), nullable=True)
    priority_score: Mapped[Decimal | None] = mapped_column(DECIMAL(5, 2), nullable=True)
    risk_score: Mapped[Decimal | None] = mapped_column(DECIMAL(5, 2), nullable=True)
    ops_cost_score: Mapped[Decimal | None] = mapped_column(DECIMAL(5, 2), nullable=True)
    demand_score: Mapped[Decimal | None] = mapped_column(DECIMAL(5, 2), nullable=True)

    # Status
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="pending"
    )

    def __repr__(self) -> str:
        return f"<Product(id={self.id}, ali_product_id={self.ali_product_id}, status={self.status})>"
