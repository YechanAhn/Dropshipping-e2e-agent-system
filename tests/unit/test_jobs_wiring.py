"""
Anti-Potemkin wiring tests for the scheduler jobs.

The original ``scheduler/jobs.py`` referenced *fictional* class/method names
(``AliExpressAffiliateAPI.get_trending_products``, ``NaverDatalabAPI``,
``NaverCommerceAPI``, ``send_telegram_message``) guarded by ``try/except
ImportError``, so every job silently no-op'd while the system "ran".

These tests assert the jobs are wired to the *real* components:

1. all 8 public job functions exist and are coroutine functions;
2. the real classes the jobs call exist *with the exact methods called*;
3. the jobs.py source text contains none of the old fictional names;
4. ``scheduler.runner`` (which imports the 8 jobs) imports cleanly;
5. ``api.app.create_app()`` builds a FastAPI app (served by ``main``).

They intentionally do **not** instantiate clients or ``get_settings()`` -- that
would require live credentials/.env. Existence + signature + source checks are
what would have caught the original bug.
"""
from __future__ import annotations

import inspect

from dropagent.agents.order_manager import OrderManager
from dropagent.clients.aliexpress.affiliate_api import AliExpressAffiliateClient
from dropagent.clients.naver.commerce_api import NaverCommerceClient
from dropagent.clients.naver.searchad_api import NaverSearchAdClient
from dropagent.clients.naver.shopping_api import NaverShoppingClient
from dropagent.clients.telegram_bot import TelegramNotifier
from dropagent.core.content_generator import ContentGenerator
from dropagent.core.matching import ProductMatcher
from dropagent.db.repositories.analytics_repo import AnalyticsRepository
from dropagent.db.repositories.order_repo import OrderRepository
from dropagent.db.repositories.product_repo import ProductRepository
from dropagent.pipeline.discovery import DiscoveryPipeline
from dropagent.pipeline.sourcing import SourcingOrchestrator
from dropagent.scheduler import jobs

JOB_NAMES = [
    "collect_ali_products_job",
    "collect_naver_trends_job",
    "update_scores_job",
    "auto_register_products_job",
    "check_orders_job",
    "monitor_price_changes_job",
    "health_check_job",
    "daily_report_job",
]

# Names that the original broken module referenced but that never existed.
FICTIONAL_NAMES = [
    "AliExpressAffiliateAPI",
    "NaverDatalabAPI",
    "NaverCommerceAPI",
    "get_trending_products",
    "send_telegram_message",
    "get_shopping_trends",
    "get_new_orders",
    "get_product_price",
]


# ─── 1. All 8 jobs exist and are coroutine functions ────────────────────


def test_all_job_functions_exist_and_are_coroutines() -> None:
    for name in JOB_NAMES:
        assert hasattr(jobs, name), f"missing job function: {name}"
        fn = getattr(jobs, name)
        assert inspect.iscoroutinefunction(fn), f"{name} must be 'async def'"
        # Jobs are scheduled with no arguments.
        sig = inspect.signature(fn)
        assert len(sig.parameters) == 0, f"{name} must take no parameters"


def test_real_idempotency_helpers_present() -> None:
    for helper in ("_log_job_run", "_acquire_job", "_complete_job", "_fail_job"):
        assert inspect.iscoroutinefunction(getattr(jobs, helper))
    assert hasattr(jobs, "SEED_KEYWORDS")
    assert isinstance(jobs.SEED_KEYWORDS, list) and jobs.SEED_KEYWORDS


# ─── 2. Real classes exist WITH the methods the jobs call ───────────────


def test_aliexpress_client_has_called_methods() -> None:
    assert hasattr(AliExpressAffiliateClient, "get_hot_products")
    assert hasattr(AliExpressAffiliateClient, "get_product_detail")
    # The old fictional method must be gone.
    assert not hasattr(AliExpressAffiliateClient, "get_trending_products")


def test_naver_commerce_client_has_called_methods() -> None:
    assert hasattr(NaverCommerceClient, "register_product")
    assert hasattr(NaverCommerceClient, "get_orders")


def test_naver_demand_clients_have_called_methods() -> None:
    assert hasattr(NaverSearchAdClient, "get_keyword_stats")
    assert hasattr(NaverShoppingClient, "search")


def test_naver_datalab_client_has_called_methods() -> None:
    from dropagent.clients.naver.datalab_api import NaverDataLabClient

    # collect_naver_trends_job constructs this and calls get_keyword_trend()
    # (via the momentum provider) then close() in its finally block.
    assert hasattr(NaverDataLabClient, "get_keyword_trend")
    assert hasattr(NaverDataLabClient, "close")


def test_pipeline_and_agents_importable_with_methods() -> None:
    assert hasattr(DiscoveryPipeline, "discover")
    assert hasattr(SourcingOrchestrator, "evaluate_candidate")
    assert hasattr(OrderManager, "poll_new_orders")
    # Collaborators the jobs construct.
    assert ProductMatcher is not None
    assert ContentGenerator is not None


def test_repositories_have_called_methods() -> None:
    assert hasattr(AnalyticsRepository, "add_trend_data")
    assert hasattr(AnalyticsRepository, "add_price_record")
    assert hasattr(ProductRepository, "list_all")
    assert hasattr(ProductRepository, "update")
    assert hasattr(ProductRepository, "count")
    assert hasattr(OrderRepository, "get_revenue_summary")
    assert hasattr(OrderRepository, "count_by_status")


def test_telegram_notifier_has_send_method() -> None:
    # daily_report / order alerts use send_message (the real method).
    assert hasattr(TelegramNotifier, "send_message")
    assert not hasattr(jobs, "send_telegram_message")


# ─── 3. jobs.py source contains NO fictional names ──────────────────────


def test_jobs_source_has_no_fictional_names() -> None:
    source = inspect.getsource(jobs)
    for fake in FICTIONAL_NAMES:
        assert fake not in source, f"fictional reference still present: {fake!r}"


def test_jobs_source_references_real_components() -> None:
    source = inspect.getsource(jobs)
    for real in (
        "DiscoveryPipeline",
        "SourcingOrchestrator",
        "OrderManager",
        "AliExpressAffiliateClient",
        "NaverCommerceClient",
        "get_hot_products",
        "get_product_detail",
        "register_product",
        "poll_new_orders",
        "TelegramNotifier",
    ):
        assert real in source, f"expected real reference missing: {real!r}"


def test_collect_naver_trends_wires_datalab_momentum() -> None:
    """collect_naver_trends_job must actually attach the DataLab momentum provider.

    Guards against a Potemkin regression where the job constructs the pipeline
    without ``momentum_provider=`` (S4 silently disabled in production).
    """
    from dropagent.core.discovery.datalab_momentum import make_datalab_momentum_provider

    source = inspect.getsource(jobs)
    assert "NaverDataLabClient" in source
    assert "make_datalab_momentum_provider" in source
    assert "momentum_provider=" in source
    assert callable(make_datalab_momentum_provider)


# ─── 4. scheduler.runner imports cleanly (its 8 imports resolve) ────────


def test_scheduler_runner_imports_cleanly() -> None:
    from dropagent.scheduler import runner

    for name in JOB_NAMES:
        assert hasattr(runner, name), f"runner failed to import job: {name}"


# ─── 5. create_app() builds a FastAPI app (served alongside scheduler) ──


def test_create_app_builds_application() -> None:
    from fastapi import FastAPI

    from dropagent.api.app import create_app

    app = create_app()
    assert isinstance(app, FastAPI)


def test_main_module_wires_scheduler_and_api() -> None:
    from dropagent import main

    source = inspect.getsource(main)
    assert "create_app" in source
    assert "uvicorn.Server" in source
    assert "uvicorn.Config" in source
