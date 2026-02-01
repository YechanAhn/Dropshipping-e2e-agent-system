"""
Trend Data Model
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DECIMAL, BigInteger, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class TrendData(Base):
    """Trend data table for storing search trends and keyword analytics"""

    __tablename__ = "trend_data"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Keyword and category
    keyword: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)

    # Metrics
    click_ratio: Mapped[Decimal] = mapped_column(DECIMAL(5, 2), nullable=False)
    search_volume: Mapped[int] = mapped_column(Integer, nullable=False)

    # Timestamp
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    def __repr__(self) -> str:
        return f"<TrendData(id={self.id}, keyword={self.keyword}, collected_at={self.collected_at})>"
