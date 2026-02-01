"""
Product Model
"""
from decimal import Decimal

from sqlalchemy import DECIMAL, BigInteger, String, Text
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
