"""
LangGraph agent state definitions for DropAgent.

Each ``TypedDict`` below represents the state schema for a LangGraph
sub-graph.  The ``Annotated[list, add_messages]`` pattern is used for
the orchestrator's ``messages`` field so that LangGraph automatically
appends new messages rather than replacing the entire list.

State classes:
    - OrchestratorState: top-level orchestration graph.
    - CollectorState: product collection sub-graph.
    - AnalyzerState: product analysis / scoring sub-graph.
    - ContentState: content generation sub-graph.
    - RegistrarState: Naver Smart Store registration sub-graph.
    - MonitorState: price / stock monitoring sub-graph.
    - OrderState: order management sub-graph.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages

# ------------------------------------------------------------------
# Orchestrator (top-level)
# ------------------------------------------------------------------

class OrchestratorState(TypedDict):
    """Top-level state for the orchestration graph.

    Attributes:
        messages: Conversation messages (auto-appended via ``add_messages``).
        current_phase: Active pipeline phase -- one of ``collect``,
            ``analyze``, ``content``, ``register``, ``monitor``.
        products_to_process: Products pending processing in the current
            phase.
        approval_required: Whether the current batch needs human
            approval before continuing.
        error_count: Cumulative error count for the current run.
    """

    messages: Annotated[list, add_messages]
    current_phase: str  # collect | analyze | content | register | monitor
    products_to_process: list[dict]
    approval_required: bool
    error_count: int


# ------------------------------------------------------------------
# Collector
# ------------------------------------------------------------------

class CollectorState(TypedDict):
    """State for the product collection sub-graph.

    Attributes:
        keywords: Search keywords to use when collecting products.
        category_ids: AliExpress category IDs to scan.
        collected_products: Products collected so far.
        collection_status: Current status -- ``pending``, ``in_progress``,
            ``completed``, or ``failed``.
    """

    keywords: list[str]
    category_ids: list[str]
    collected_products: list[dict]
    collection_status: str  # pending | in_progress | completed | failed


# ------------------------------------------------------------------
# Analyzer
# ------------------------------------------------------------------

class AnalyzerState(TypedDict):
    """State for the product analysis / scoring sub-graph.

    Attributes:
        products: Raw products to analyse.
        scored_products: Products that have been scored and ranked.
        analysis_status: Current status -- ``pending``, ``in_progress``,
            ``completed``, or ``failed``.
    """

    products: list[dict]
    scored_products: list[dict]
    analysis_status: str  # pending | in_progress | completed | failed


# ------------------------------------------------------------------
# Content generator
# ------------------------------------------------------------------

class ContentState(TypedDict):
    """State for the content generation sub-graph.

    Attributes:
        products: Products that need content generated.
        generated_content: Mapping of product ID to generated content
            payloads (title, description, images, etc.).
        content_status: Current status.
    """

    products: list[dict]
    generated_content: list[dict]
    content_status: str  # pending | in_progress | completed | failed


# ------------------------------------------------------------------
# Registrar
# ------------------------------------------------------------------

class RegistrarState(TypedDict):
    """State for the Naver Smart Store registration sub-graph.

    Attributes:
        products_to_register: Products ready for registration.
        registered_products: Successfully registered products with
            their Naver product IDs.
        failed_products: Products that failed registration along with
            error details.
        registration_status: Current status.
    """

    products_to_register: list[dict]
    registered_products: list[dict]
    failed_products: list[dict]
    registration_status: str  # pending | in_progress | completed | failed


# ------------------------------------------------------------------
# Monitor
# ------------------------------------------------------------------

class MonitorState(TypedDict):
    """State for the price / stock monitoring sub-graph.

    Attributes:
        monitored_products: Products currently being monitored.
        price_changes: Detected price changes since the last check.
        stock_alerts: Out-of-stock or low-stock alerts.
        monitor_status: Current status.
    """

    monitored_products: list[dict]
    price_changes: list[dict]
    stock_alerts: list[dict]
    monitor_status: str  # pending | in_progress | completed | failed


# ------------------------------------------------------------------
# Order manager
# ------------------------------------------------------------------

class OrderState(TypedDict):
    """State for the order management sub-graph.

    Attributes:
        pending_orders: Orders awaiting processing.
        processed_orders: Orders that have been fulfilled or forwarded.
        order_errors: Orders that encountered errors.
        order_status: Current status.
    """

    pending_orders: list[dict]
    processed_orders: list[dict]
    order_errors: list[dict]
    order_status: str  # pending | in_progress | completed | failed
