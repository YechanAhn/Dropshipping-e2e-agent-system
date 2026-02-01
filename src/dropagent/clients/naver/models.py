"""
Naver API response models.

Pydantic models for parsing and validating responses from the Naver Shopping
Search API, the Naver Commerce API, and the Naver DataLab Shopping Insight API.
"""


from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Naver Shopping Search API models
# ---------------------------------------------------------------------------


class NaverShoppingItem(BaseModel):
    """Single item from Naver Shopping search results."""

    title: str = Field(default="", description="Product title (may contain HTML tags)")
    link: str = Field(default="", description="Product detail page URL")
    image: str = Field(default="", description="Product thumbnail image URL")
    lowest_price: int = Field(default=0, alias="lprice", description="Lowest price (KRW)")
    highest_price: int = Field(default=0, alias="hprice", description="Highest price (KRW)")
    mall_name: str = Field(default="", alias="mallName", description="Store / mall name")
    product_id: str = Field(default="", alias="productId", description="Naver product ID")
    product_type: int = Field(default=0, alias="productType", description="Product type code")
    category1: str = Field(default="", description="Top-level category name")
    category2: str = Field(default="", description="Second-level category name")
    category3: str = Field(default="", description="Third-level category name")
    category4: str = Field(default="", description="Fourth-level category name")

    model_config = {"populate_by_name": True}


class NaverShoppingResult(BaseModel):
    """Search result envelope from Naver Shopping Search API."""

    items: list[NaverShoppingItem] = Field(default_factory=list, description="List of matching products")
    total: int = Field(default=0, description="Total number of search results")
    start: int = Field(default=1, description="Starting offset of the current page")
    display: int = Field(default=10, description="Number of items returned")


# ---------------------------------------------------------------------------
# Naver Commerce API models
# ---------------------------------------------------------------------------


class NaverOriginProduct(BaseModel):
    """Origin product nested inside a Naver Commerce product record."""

    status_type: str | None = Field(default=None, alias="statusType", description="Product status")
    sale_type: str | None = Field(default=None, alias="saleType", description="Sale type")
    leaf_category_id: str | None = Field(default=None, alias="leafCategoryId", description="Leaf category ID")
    name: str | None = Field(default=None, description="Product name")
    sale_price: int | None = Field(default=None, alias="salePrice", description="Sale price (KRW)")
    stock_quantity: int | None = Field(default=None, alias="stockQuantity", description="Inventory quantity")
    detail_content: str | None = Field(default=None, alias="detailContent", description="Product detail HTML")

    model_config = {"populate_by_name": True}


class NaverCommerceProduct(BaseModel):
    """Product record from the Naver Commerce API."""

    channel_product_id: str = Field(default="", alias="channelProductId", description="Channel-specific product ID")
    origin_product: NaverOriginProduct | None = Field(
        default=None, alias="originProduct", description="Nested origin product data"
    )
    smart_store_channel_product_id: str | None = Field(
        default=None,
        alias="smartStoreChannelProductId",
        description="SmartStore channel product ID",
    )
    status: str | None = Field(default=None, description="Overall product status")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Naver DataLab Shopping Insight API models
# ---------------------------------------------------------------------------


class NaverTrendItem(BaseModel):
    """Single data point in a DataLab trend series."""

    period: str = Field(default="", description="Date or period string (e.g. '2024-01')")
    ratio: float = Field(default=0.0, description="Relative search ratio (0-100)")
    group: str = Field(default="", description="Keyword or category group name")


class NaverTrendGroup(BaseModel):
    """A group (keyword/category) with its trend data points."""

    title: str = Field(default="", description="Group title (keyword or category)")
    keywords: list[str] = Field(default_factory=list, description="Keywords belonging to this group")
    data: list[NaverTrendItem] = Field(default_factory=list, description="Trend data points")


class NaverTrendResult(BaseModel):
    """Response from the Naver DataLab Shopping Insight API."""

    results: list[NaverTrendGroup] = Field(default_factory=list, description="List of trend groups")
    start_date: str = Field(default="", description="Query start date (YYYY-MM-DD)")
    end_date: str = Field(default="", description="Query end date (YYYY-MM-DD)")
