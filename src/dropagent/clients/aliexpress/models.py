"""
AliExpress API response models.

Pydantic models for parsing and validating AliExpress Affiliate API responses
including product search results, product details, and related data structures.
"""

from decimal import Decimal

from pydantic import BaseModel, Field


class AliPriceInfo(BaseModel):
    """Price information for an AliExpress product."""

    original_price: Decimal = Field(..., description="Original listed price")
    sale_price: Decimal = Field(..., description="Current sale price")


class AliShippingInfo(BaseModel):
    """Shipping information for an AliExpress product."""

    days: int = Field(default=0, description="Estimated delivery days")
    cost: Decimal = Field(default=Decimal("0.00"), description="Shipping cost")


class AliSellerInfo(BaseModel):
    """Seller information for an AliExpress product."""

    id: str = Field(default="", description="Seller store ID")
    rating: Decimal = Field(default=Decimal("0.0"), description="Seller positive feedback rating")
    name: str = Field(default="", description="Seller store name")


class AliProduct(BaseModel):
    """AliExpress product from search or hot products endpoint."""

    product_id: str = Field(..., description="AliExpress product ID")
    title: str = Field(..., description="Product title")
    price: AliPriceInfo = Field(..., description="Product pricing information")
    currency: str = Field(default="USD", description="Price currency code")
    category_id: str | None = Field(default=None, description="Product category ID")
    category_name: str | None = Field(default=None, description="Product category name")
    image_url: str = Field(default="", description="Main product image URL")
    product_url: str = Field(default="", description="Affiliate product URL")
    rating: Decimal = Field(default=Decimal("0.0"), description="Product average rating")
    order_count: int = Field(default=0, description="Total order count")
    shipping_info: AliShippingInfo = Field(default_factory=AliShippingInfo, description="Shipping details")
    seller_info: AliSellerInfo = Field(default_factory=AliSellerInfo, description="Seller details")


class AliSearchResult(BaseModel):
    """Search result response from AliExpress Affiliate API."""

    products: list[AliProduct] = Field(default_factory=list, description="List of matching products")
    total_count: int = Field(default=0, description="Total number of matching products")
    current_page: int = Field(default=1, description="Current page number")


class AliProductVariant(BaseModel):
    """Product option/variant information."""

    sku_id: str = Field(default="", description="SKU identifier")
    name: str = Field(default="", description="Variant option name")
    value: str = Field(default="", description="Variant option value")
    image_url: str | None = Field(default=None, description="Variant image URL")
    price: Decimal | None = Field(default=None, description="Variant specific price")
    stock: int | None = Field(default=None, description="Available stock quantity")


class AliProductDetail(AliProduct):
    """Extended product detail with description, variants, and review info."""

    description: str = Field(default="", description="Full product description (HTML)")
    options: list[AliProductVariant] = Field(default_factory=list, description="Product variants/options")
    reviews_count: int = Field(default=0, description="Total number of product reviews")
