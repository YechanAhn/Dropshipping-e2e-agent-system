"""
Product Repository - Database operations for the Product model.
"""
from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dropagent.db.models import Product
from dropagent.utils.exceptions import DatabaseError
from dropagent.utils.logging import get_logger

logger = get_logger(__name__)


class ProductRepository:
    """Repository for Product CRUD operations and queries."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, data: dict) -> Product:
        """
        Create a new product.

        Args:
            data: Dictionary of product fields.

        Returns:
            The newly created Product instance.

        Raises:
            DatabaseError: On duplicate ali_product_id/naver_product_id or other DB errors.
        """
        try:
            product = Product(**data)
            self.session.add(product)
            await self.session.flush()
            await self.session.refresh(product)
            logger.info(
                "product_created",
                product_id=product.id,
                ali_product_id=product.ali_product_id,
            )
            return product
        except IntegrityError as e:
            await self.session.rollback()
            logger.warning(
                "product_create_integrity_error",
                data=data,
                error=str(e),
            )
            raise DatabaseError(
                message="Product with this identifier already exists",
                operation="create",
                table="products",
                details={"data": data},
                original_error=e,
            ) from e
        except Exception as e:
            await self.session.rollback()
            logger.error(
                "product_create_error",
                data=data,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to create product",
                operation="create",
                table="products",
                original_error=e,
            ) from e

    async def get_by_id(self, product_id: int) -> Product | None:
        """
        Get a product by its primary key.

        Args:
            product_id: The product ID.

        Returns:
            Product instance or None if not found.
        """
        try:
            stmt = select(Product).where(Product.id == product_id)
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(
                "product_get_by_id_error",
                product_id=product_id,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to get product by ID",
                operation="get_by_id",
                table="products",
                details={"product_id": product_id},
                original_error=e,
            ) from e

    async def get_by_ali_id(self, ali_product_id: str) -> Product | None:
        """
        Get a product by its AliExpress product ID.

        Args:
            ali_product_id: The AliExpress product identifier.

        Returns:
            Product instance or None if not found.
        """
        try:
            stmt = select(Product).where(Product.ali_product_id == ali_product_id)
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(
                "product_get_by_ali_id_error",
                ali_product_id=ali_product_id,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to get product by AliExpress ID",
                operation="get_by_ali_id",
                table="products",
                details={"ali_product_id": ali_product_id},
                original_error=e,
            ) from e

    async def get_by_naver_id(self, naver_product_id: str) -> Product | None:
        """
        Get a product by its Naver SmartStore product ID.

        Args:
            naver_product_id: The Naver product identifier.

        Returns:
            Product instance or None if not found.
        """
        try:
            stmt = select(Product).where(Product.naver_product_id == naver_product_id)
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(
                "product_get_by_naver_id_error",
                naver_product_id=naver_product_id,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to get product by Naver ID",
                operation="get_by_naver_id",
                table="products",
                details={"naver_product_id": naver_product_id},
                original_error=e,
            ) from e

    async def list_all(
        self,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Product]:
        """
        List products with optional status filtering and pagination.

        Args:
            status: Optional status filter.
            limit: Maximum number of products to return.
            offset: Number of products to skip.

        Returns:
            List of Product instances.
        """
        try:
            stmt = select(Product).order_by(Product.created_at.desc())
            if status is not None:
                stmt = stmt.where(Product.status == status)
            stmt = stmt.limit(limit).offset(offset)
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(
                "product_list_all_error",
                status=status,
                limit=limit,
                offset=offset,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to list products",
                operation="list_all",
                table="products",
                original_error=e,
            ) from e

    async def list_by_priority(
        self,
        min_score: float = 0,
        limit: int = 50,
    ) -> list[Product]:
        """
        List products ordered by priority_score descending, filtered by minimum score.

        Args:
            min_score: Minimum priority score threshold.
            limit: Maximum number of products to return.

        Returns:
            List of Product instances ordered by priority_score DESC.
        """
        try:
            stmt = (
                select(Product)
                .where(Product.priority_score >= min_score)
                .where(Product.priority_score.is_not(None))
                .order_by(Product.priority_score.desc())
                .limit(limit)
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(
                "product_list_by_priority_error",
                min_score=min_score,
                limit=limit,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to list products by priority",
                operation="list_by_priority",
                table="products",
                original_error=e,
            ) from e

    async def update(self, product_id: int, data: dict) -> Product:
        """
        Update a product by ID with the given data.

        Args:
            product_id: The product ID to update.
            data: Dictionary of fields to update.

        Returns:
            The updated Product instance.

        Raises:
            DatabaseError: If the product is not found or update fails.
        """
        try:
            product = await self.get_by_id(product_id)
            if product is None:
                raise DatabaseError(
                    message=f"Product with id {product_id} not found",
                    operation="update",
                    table="products",
                    details={"product_id": product_id},
                )
            for key, value in data.items():
                if hasattr(product, key):
                    setattr(product, key, value)
            await self.session.flush()
            await self.session.refresh(product)
            logger.info(
                "product_updated",
                product_id=product_id,
                updated_fields=list(data.keys()),
            )
            return product
        except DatabaseError:
            raise
        except IntegrityError as e:
            await self.session.rollback()
            logger.warning(
                "product_update_integrity_error",
                product_id=product_id,
                data=data,
                error=str(e),
            )
            raise DatabaseError(
                message="Product update violates unique constraint",
                operation="update",
                table="products",
                details={"product_id": product_id, "data": data},
                original_error=e,
            ) from e
        except Exception as e:
            await self.session.rollback()
            logger.error(
                "product_update_error",
                product_id=product_id,
                data=data,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to update product",
                operation="update",
                table="products",
                details={"product_id": product_id},
                original_error=e,
            ) from e

    async def update_scores(
        self,
        product_id: int,
        margin_rate,
        priority_score,
        risk_score,
        ops_cost_score,
        demand_score,
    ) -> Product:
        """
        Update all scoring fields for a product.

        Args:
            product_id: The product ID.
            margin_rate: New margin rate value.
            priority_score: New priority score value.
            risk_score: New risk score value.
            ops_cost_score: New operational cost score value.
            demand_score: New demand score value.

        Returns:
            The updated Product instance.

        Raises:
            DatabaseError: If product not found or update fails.
        """
        return await self.update(
            product_id,
            {
                "margin_rate": margin_rate,
                "priority_score": priority_score,
                "risk_score": risk_score,
                "ops_cost_score": ops_cost_score,
                "demand_score": demand_score,
            },
        )

    async def update_status(self, product_id: int, status: str) -> Product:
        """
        Update the status of a product.

        Args:
            product_id: The product ID.
            status: New status value.

        Returns:
            The updated Product instance.

        Raises:
            DatabaseError: If product not found or update fails.
        """
        return await self.update(product_id, {"status": status})

    async def delete(self, product_id: int) -> bool:
        """
        Delete a product by ID.

        Args:
            product_id: The product ID to delete.

        Returns:
            True if the product was deleted, False if not found.
        """
        try:
            product = await self.get_by_id(product_id)
            if product is None:
                return False
            await self.session.delete(product)
            await self.session.flush()
            logger.info("product_deleted", product_id=product_id)
            return True
        except Exception as e:
            await self.session.rollback()
            logger.error(
                "product_delete_error",
                product_id=product_id,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to delete product",
                operation="delete",
                table="products",
                details={"product_id": product_id},
                original_error=e,
            ) from e

    async def count(self, status: str | None = None) -> int:
        """
        Count products, optionally filtered by status.

        Args:
            status: Optional status filter.

        Returns:
            Number of matching products.
        """
        try:
            stmt = select(func.count(Product.id))
            if status is not None:
                stmt = stmt.where(Product.status == status)
            result = await self.session.execute(stmt)
            return result.scalar_one()
        except Exception as e:
            logger.error(
                "product_count_error",
                status=status,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to count products",
                operation="count",
                table="products",
                original_error=e,
            ) from e

    async def search(self, query: str, limit: int = 20) -> list[Product]:
        """
        Search products by English or Korean name using case-insensitive LIKE.

        Args:
            query: The search string.
            limit: Maximum number of results.

        Returns:
            List of matching Product instances.
        """
        try:
            search_pattern = f"%{query}%"
            stmt = (
                select(Product)
                .where(
                    or_(
                        Product.product_name_en.ilike(search_pattern),
                        Product.product_name_ko.ilike(search_pattern),
                    )
                )
                .order_by(Product.priority_score.desc().nulls_last())
                .limit(limit)
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as e:
            logger.error(
                "product_search_error",
                query=query,
                limit=limit,
                error=str(e),
            )
            raise DatabaseError(
                message="Failed to search products",
                operation="search",
                table="products",
                details={"query": query},
                original_error=e,
            ) from e
