"""add lowest-price tracking columns to products

Revision ID: a1b2c3d4e5f6
Revises: 7421d5a29482
Create Date: 2026-06-14 06:40:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "7421d5a29482"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 최저가 노출 추적: 초기 사업자는 최저가를 맞춰야 노출 가능.
    op.add_column("products", sa.Column("naver_catalog_lowest", sa.DECIMAL(10, 2), nullable=True))
    op.add_column("products", sa.Column("naver_price_min_market", sa.DECIMAL(10, 2), nullable=True))
    op.add_column(
        "products",
        sa.Column("is_price_lowest", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("products", sa.Column("price_floor", sa.DECIMAL(10, 2), nullable=True))
    op.add_column("products", sa.Column("pricing_strategy", sa.String(length=20), nullable=True))
    op.add_column("products", sa.Column("last_repriced_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "last_repriced_at")
    op.drop_column("products", "pricing_strategy")
    op.drop_column("products", "price_floor")
    op.drop_column("products", "is_price_lowest")
    op.drop_column("products", "naver_price_min_market")
    op.drop_column("products", "naver_catalog_lowest")
