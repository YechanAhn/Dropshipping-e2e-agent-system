"""
Price History Model
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DECIMAL, BigInteger, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class PriceHistory(Base):
    """Price history table for tracking product price changes over time"""

    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Foreign key to products
    product_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False
    )

    # Pricing
    price_ali: Mapped[Decimal] = mapped_column(DECIMAL(10, 2), nullable=False)
    price_naver: Mapped[Decimal] = mapped_column(DECIMAL(10, 2), nullable=False)

    # Exchange rate
    exchange_rate: Mapped[Decimal] = mapped_column(DECIMAL(8, 4), nullable=False)

    # Timestamp
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    def __repr__(self) -> str:
        return f"<PriceHistory(id={self.id}, product_id={self.product_id}, recorded_at={self.recorded_at})>"
