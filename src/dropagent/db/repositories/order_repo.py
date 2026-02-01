"""
Order Repository - Database operations for the Order model.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dropagent.db.models import Order
from dropagent.utils.exceptions import DatabaseError
from dropagent.utils.logging import get_logger

logger = get_logger(__name__)


class OrderRepository:
    """Repository for Order CRUD operations and queries."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, data: dict) -> Order:
        """
        Create a new order.

        Args:
            data: Dictionary of order fields.

        Returns:
            The newly created Order instance.

        Raises:
            DatabaseError: On duplicate naver_order_id or other DB errors.
        """
        try:
            order = Order(**data)
            self.session.add(order)
            await self.session.flush()
            await self.session.refresh(order)
            logger.info(
                "order_created",
                order_id=order.id,
                naver_order_id=order.naver_order_id,
            )
            return order
        except IntegrityError as e:
            await self.session.rollback()
            logger.warning(
                "order_create_integrity_error",
                data=data,
                error=str(e),
            )
            raise DatabaseError(
                message="Order with this identifier already exists",
                operation="create",
                table="orders",
                details={"data": data},
                original_error=e,
            ) from e
        except Exception as e:
            await self.session.rollback()
            logger.error(
                "order_create_error",
                data=data,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to create order",
                operation="create",
                table="orders",
                original_error=e,
            ) from e

    async def get_by_id(self, order_id: int) -> Order | None:
        """
        Get an order by its primary key.

        Args:
            order_id: The order ID.

        Returns:
            Order instance or None if not found.
        """
        try:
            stmt = select(Order).where(Order.id == order_id)
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(
                "order_get_by_id_error",
                order_id=order_id,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to get order by ID",
                operation="get_by_id",
                table="orders",
                details={"order_id": order_id},
                original_error=e,
            ) from e

    async def get_by_naver_id(self, naver_order_id: str) -> Order | None:
        """
        Get an order by its Naver order ID.

        Args:
            naver_order_id: The Naver order identifier.

        Returns:
            Order instance or None if not found.
        """
        try:
            stmt = select(Order).where(Order.naver_order_id == naver_order_id)
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(
                "order_get_by_naver_id_error",
                naver_order_id=naver_order_id,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to get order by Naver ID",
                operation="get_by_naver_id",
                table="orders",
                details={"naver_order_id": naver_order_id},
                original_error=e,
            ) from e

    async def list_by_status(self, status: str, limit: int = 100) -> list[Order]:
        """
        List orders filtered by status.

        Args:
            status: The order status to filter by.
            limit: Maximum number of orders to return.

        Returns:
            List of Order instances with the given status.
        """
        try:
            stmt = (
                select(Order)
                .where(Order.status == status)
                .order_by(Order.created_at.desc())
                .limit(limit)
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(
                "order_list_by_status_error",
                status=status,
                limit=limit,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to list orders by status",
                operation="list_by_status",
                table="orders",
                original_error=e,
            ) from e

    async def list_recent(self, hours: int = 24, limit: int = 100) -> list[Order]:
        """
        List orders created within the specified number of hours.

        Args:
            hours: Number of hours to look back from now.
            limit: Maximum number of orders to return.

        Returns:
            List of recent Order instances.
        """
        try:
            cutoff = datetime.now(UTC) - timedelta(hours=hours)
            stmt = (
                select(Order)
                .where(Order.created_at >= cutoff)
                .order_by(Order.created_at.desc())
                .limit(limit)
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(
                "order_list_recent_error",
                hours=hours,
                limit=limit,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to list recent orders",
                operation="list_recent",
                table="orders",
                original_error=e,
            ) from e

    async def update_status(self, order_id: int, status: str) -> Order:
        """
        Update the status of an order.

        Args:
            order_id: The order ID.
            status: New status value.

        Returns:
            The updated Order instance.

        Raises:
            DatabaseError: If order not found or update fails.
        """
        try:
            order = await self.get_by_id(order_id)
            if order is None:
                raise DatabaseError(
                    message=f"Order with id {order_id} not found",
                    operation="update_status",
                    table="orders",
                    details={"order_id": order_id},
                )
            order.status = status
            await self.session.flush()
            await self.session.refresh(order)
            logger.info(
                "order_status_updated",
                order_id=order_id,
                new_status=status,
            )
            return order
        except DatabaseError:
            raise
        except Exception as e:
            await self.session.rollback()
            logger.error(
                "order_update_status_error",
                order_id=order_id,
                status=status,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to update order status",
                operation="update_status",
                table="orders",
                details={"order_id": order_id, "status": status},
                original_error=e,
            ) from e

    async def update_ali_order_id(self, order_id: int, ali_order_id: str) -> Order:
        """
        Set the AliExpress order ID on an existing order.

        Args:
            order_id: The order ID.
            ali_order_id: The AliExpress order identifier.

        Returns:
            The updated Order instance.

        Raises:
            DatabaseError: If order not found or update fails.
        """
        try:
            order = await self.get_by_id(order_id)
            if order is None:
                raise DatabaseError(
                    message=f"Order with id {order_id} not found",
                    operation="update_ali_order_id",
                    table="orders",
                    details={"order_id": order_id},
                )
            order.ali_order_id = ali_order_id
            await self.session.flush()
            await self.session.refresh(order)
            logger.info(
                "order_ali_id_updated",
                order_id=order_id,
                ali_order_id=ali_order_id,
            )
            return order
        except DatabaseError:
            raise
        except Exception as e:
            await self.session.rollback()
            logger.error(
                "order_update_ali_order_id_error",
                order_id=order_id,
                ali_order_id=ali_order_id,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to update AliExpress order ID",
                operation="update_ali_order_id",
                table="orders",
                details={"order_id": order_id, "ali_order_id": ali_order_id},
                original_error=e,
            ) from e

    async def count_by_status(self) -> dict[str, int]:
        """
        Get a count of orders grouped by status.

        Returns:
            Dictionary mapping status strings to their counts.
        """
        try:
            stmt = (
                select(Order.status, func.count(Order.id))
                .group_by(Order.status)
            )
            result = await self.session.execute(stmt)
            return {row[0]: row[1] for row in result.all()}
        except Exception as e:
            logger.error(
                "order_count_by_status_error",
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to count orders by status",
                operation="count_by_status",
                table="orders",
                original_error=e,
            ) from e

    async def get_revenue_summary(self, days: int = 30) -> dict:
        """
        Get revenue summary for the specified number of days.

        Args:
            days: Number of days to look back.

        Returns:
            Dictionary with total_revenue, total_orders, and avg_order_value.
        """
        try:
            cutoff = datetime.now(UTC) - timedelta(days=days)
            stmt = select(
                func.coalesce(func.sum(Order.total_price), 0).label("total_revenue"),
                func.count(Order.id).label("total_orders"),
                func.coalesce(func.avg(Order.total_price), 0).label("avg_order_value"),
            ).where(Order.created_at >= cutoff)

            result = await self.session.execute(stmt)
            row = result.one()
            return {
                "total_revenue": float(row.total_revenue),
                "total_orders": row.total_orders,
                "avg_order_value": float(row.avg_order_value),
            }
        except Exception as e:
            logger.error(
                "order_get_revenue_summary_error",
                days=days,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to get revenue summary",
                operation="get_revenue_summary",
                table="orders",
                original_error=e,
            ) from e
