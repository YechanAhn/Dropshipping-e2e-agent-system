"""
Product Performance Model
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import DECIMAL, BigInteger, Date, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class ProductPerformance(Base):
    """Product performance table for tracking product metrics over time"""

    __tablename__ = "product_performance"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Foreign key to products
    product_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False
    )

    # Performance metrics
    impressions: Mapped[int] = mapped_column(Integer, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False)
    conversions: Mapped[int] = mapped_column(Integer, nullable=False)
    revenue: Mapped[Decimal] = mapped_column(DECIMAL(10, 2), nullable=False)

    # Date of record
    recorded_at: Mapped[date] = mapped_column(Date, nullable=False)

    # Unique constraint on product_id and recorded_at
    __table_args__ = (
        UniqueConstraint("product_id", "recorded_at", name="uq_product_performance_product_date"),
    )

    def __repr__(self) -> str:
        return f"<ProductPerformance(id={self.id}, product_id={self.product_id}, recorded_at={self.recorded_at})>"
