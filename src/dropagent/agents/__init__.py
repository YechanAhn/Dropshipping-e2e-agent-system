"""
Agent package for DropAgent.

Contains LangGraph-based agent sub-graphs and their shared state
definitions.  Each agent handles a specific phase of the dropshipping
pipeline:

    - **orchestrator**: Top-level coordination graph.
    - **collector**: AliExpress product collection.
    - **analyzer**: Product scoring and ranking.
    - **content**: Content generation (translation, images, descriptions).
    - **registrar**: Naver Smart Store product registration.
    - **monitor**: Price and stock monitoring.
    - **order_manager**: Order forwarding and fulfilment tracking.

State schemas used by the graphs are defined in :mod:`dropagent.agents.states`.
"""

from dropagent.agents.states import (
    AnalyzerState,
    CollectorState,
    ContentState,
    MonitorState,
    OrchestratorState,
    OrderState,
    RegistrarState,
)

__all__ = [
    # State definitions
    "OrchestratorState",
    "CollectorState",
    "AnalyzerState",
    "ContentState",
    "RegistrarState",
    "MonitorState",
    "OrderState",
]
