"""
Order Model
"""
from decimal import Decimal

from sqlalchemy import DECIMAL, BigInteger, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from . import Base, TimestampMixin


class Order(Base, TimestampMixin):
    """Order table for storing Naver and AliExpress order information"""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Order identifiers
    naver_order_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    ali_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Foreign key to products
    product_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False
    )

    # Order details
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    total_price: Mapped[Decimal] = mapped_column(DECIMAL(10, 2), nullable=False)

    # Status: new, approved, processing, shipped, delivered, cancelled
    status: Mapped[str] = mapped_column(String(50), nullable=False)

    def __repr__(self) -> str:
        return f"<Order(id={self.id}, naver_order_id={self.naver_order_id}, status={self.status})>"
