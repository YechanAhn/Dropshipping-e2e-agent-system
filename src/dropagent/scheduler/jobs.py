"""
스케줄러 작업 정의 모듈

APScheduler에 의해 주기적으로 실행되는 비동기 작업들을 정의합니다.
각 작업은 멱등성을 보장하며, 구조화된 로깅과 에러 처리를 포함합니다.
"""

import time
import traceback
from datetime import UTC, datetime, timedelta

from dropagent.config import get_settings
from dropagent.core.idempotency import IdempotencyManager
from dropagent.db.session import get_db_session
from dropagent.utils.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _log_job_run(
    job_type: str,
    status: str,
    duration_ms: float,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    """
    작업 실행 결과를 agent_logs 테이블에 기록합니다.

    별도의 DB 세션을 사용하여, 호출자의 트랜잭션 상태와 무관하게 로그를 남깁니다.
    """
    from dropagent.db.models.agent_log import AgentLog

    try:
        async with get_db_session() as session:
            log_entry = AgentLog(
                agent_name="scheduler",
                job_type=job_type,
                status=status,
                message=error if error else f"Completed in {duration_ms:.0f}ms",
                log_metadata=result,
            )
            session.add(log_entry)
    except Exception as log_exc:
        logger.error(
            "job_log_write_failed",
            job_type=job_type,
            error=str(log_exc),
        )


async def _acquire_job(job_type: str, idempotency_key: str) -> bool:
    """
    멱등성 키를 확인하여 중복 실행을 방지합니다.
    IdempotencyManager.check_and_acquire를 사용합니다.

    Returns:
        True if the job should proceed, False if it should be skipped.
    """
    async with get_db_session() as session:
        acquired = await IdempotencyManager.check_and_acquire(
            session, idempotency_key, job_type=job_type,
        )
        if not acquired:
            logger.info("job_skipped_idempotent", job_type=job_type, key=idempotency_key[:16])
        return acquired


async def _complete_job(idempotency_key: str, output_result: dict) -> None:
    """작업을 완료 상태로 업데이트합니다."""
    async with get_db_session() as session:
        await IdempotencyManager.mark_completed(session, idempotency_key, result=output_result)


async def _fail_job(idempotency_key: str, error_message: str) -> None:
    """작업을 실패 상태로 업데이트합니다."""
    try:
        async with get_db_session() as session:
            await IdempotencyManager.mark_failed(session, idempotency_key, error=error_message)
    except Exception as exc:
        logger.error("job_mark_failed_error", error=str(exc))


# ---------------------------------------------------------------------------
# Scheduled jobs
# ---------------------------------------------------------------------------


async def collect_ali_products_job() -> None:
    """
    알리익스프레스 상품 수집 (6시간마다 실행).

    Affiliate API를 사용하여 트렌드 카테고리의 상품을 수집하고
    DB에 저장합니다. 멱등성 키로 중복 수집을 방지합니다.
    """
    job_type = "collect_ali_products"
    idempotency_key = IdempotencyManager.generate_key(job_type, "batch")
    start = time.monotonic()

    logger.info("job_started", job_type=job_type, idempotency_key=idempotency_key[:16])

    try:
        # Idempotency check
        should_proceed = await _acquire_job(job_type, idempotency_key)
        if not should_proceed:
            return

        settings = get_settings()
        collected_count = 0

        # --- Actual work ---
        try:
            from dropagent.clients.aliexpress.affiliate_api import AliExpressAffiliateAPI

            ali_client = AliExpressAffiliateAPI(settings)
            products = await ali_client.get_trending_products(
                count=settings.app.batch_size,
            )
            collected_count = len(products) if products else 0
        except (ImportError, AttributeError):
            logger.warning("job_client_unavailable", job_type=job_type, client="AliExpressAffiliateAPI")

        await _complete_job(idempotency_key, {"collected_count": collected_count})

        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "job_completed",
            job_type=job_type,
            collected_count=collected_count,
            duration_ms=round(duration_ms, 1),
        )
        await _log_job_run(job_type, "completed", duration_ms, {"collected_count": collected_count})

    except Exception as exc:
        duration_ms = (time.monotonic() - start) * 1000
        logger.error(
            "job_failed",
            job_type=job_type,
            error=str(exc),
            traceback=traceback.format_exc(),
            duration_ms=round(duration_ms, 1),
        )
        await _fail_job(idempotency_key, str(exc))
        await _log_job_run(job_type, "failed", duration_ms, error=str(exc))


async def collect_naver_trends_job() -> None:
    """
    네이버 트렌드 데이터 수집 (12시간마다 실행).

    네이버 DataLab API를 사용하여 인기 검색어와 카테고리 트렌드를 수집합니다.
    """
    job_type = "collect_naver_trends"
    idempotency_key = IdempotencyManager.generate_key(job_type, "batch")
    start = time.monotonic()

    logger.info("job_started", job_type=job_type, idempotency_key=idempotency_key[:16])

    try:
        should_proceed = await _acquire_job(job_type, idempotency_key)
        if not should_proceed:
            return

        settings = get_settings()
        trend_count = 0

        try:
            from dropagent.clients.naver.datalab_api import NaverDatalabAPI

            naver_client = NaverDatalabAPI(settings)
            trends = await naver_client.get_shopping_trends()
            trend_count = len(trends) if trends else 0
        except (ImportError, AttributeError):
            logger.warning("job_client_unavailable", job_type=job_type, client="NaverDatalabAPI")

        await _complete_job(idempotency_key, {"trend_count": trend_count})

        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "job_completed",
            job_type=job_type,
            trend_count=trend_count,
            duration_ms=round(duration_ms, 1),
        )
        await _log_job_run(job_type, "completed", duration_ms, {"trend_count": trend_count})

    except Exception as exc:
        duration_ms = (time.monotonic() - start) * 1000
        logger.error(
            "job_failed",
            job_type=job_type,
            error=str(exc),
            traceback=traceback.format_exc(),
            duration_ms=round(duration_ms, 1),
        )
        await _fail_job(idempotency_key, str(exc))
        await _log_job_run(job_type, "failed", duration_ms, error=str(exc))


async def update_scores_job() -> None:
    """
    모든 상품의 우선순위 스코어 재계산 (6시간마다 실행).

    마진율, 수요, 리스크, 운영비용, 공급사 신뢰도를 기반으로
    priority_score를 갱신합니다.
    """
    job_type = "update_scores"
    idempotency_key = IdempotencyManager.generate_key(job_type, "batch")
    start = time.monotonic()

    logger.info("job_started", job_type=job_type, idempotency_key=idempotency_key[:16])

    try:
        should_proceed = await _acquire_job(job_type, idempotency_key)
        if not should_proceed:
            return

        updated_count = 0

        try:
            from sqlalchemy import select

            from dropagent.core.priority_scorer import PriorityScorer
            from dropagent.db.models.product import Product

            scorer = PriorityScorer()

            async with get_db_session() as session:
                result = await session.execute(
                    select(Product).where(
                        Product.status.in_(["pending", "approved", "registered"])
                    )
                )
                products = result.scalars().all()

                for product in products:
                    try:
                        margin = min(max(float(product.margin_rate or 0) / 100.0, 0.0), 1.0)
                        demand = min(max(float(product.demand_score or 0), 0.0), 1.0)
                        risk = min(max(float(product.risk_score or 0), 0.0), 1.0)
                        ops_cost = min(max(float(product.ops_cost_score or 0), 0.0), 1.0)
                        supplier = 0.5  # default supplier score

                        breakdown = scorer.calculate_score(
                            margin=margin,
                            demand=demand,
                            risk=risk,
                            ops_cost=ops_cost,
                            supplier=supplier,
                        )
                        product.priority_score = round(breakdown.final_score * 100, 2)
                        updated_count += 1
                    except Exception as score_exc:
                        logger.warning(
                            "score_calculation_failed",
                            product_id=product.id,
                            error=str(score_exc),
                        )
        except (ImportError, AttributeError):
            logger.warning("job_dependency_unavailable", job_type=job_type)

        await _complete_job(idempotency_key, {"updated_count": updated_count})

        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "job_completed",
            job_type=job_type,
            updated_count=updated_count,
            duration_ms=round(duration_ms, 1),
        )
        await _log_job_run(job_type, "completed", duration_ms, {"updated_count": updated_count})

    except Exception as exc:
        duration_ms = (time.monotonic() - start) * 1000
        logger.error(
            "job_failed",
            job_type=job_type,
            error=str(exc),
            traceback=traceback.format_exc(),
            duration_ms=round(duration_ms, 1),
        )
        await _fail_job(idempotency_key, str(exc))
        await _log_job_run(job_type, "failed", duration_ms, error=str(exc))


async def auto_register_products_job() -> None:
    """
    승인된 상품 자동 등록 (1시간마다 실행).

    priority_score가 임계값 이상이고 status가 'approved'인 상품을
    네이버 스마트스토어에 자동 등록합니다.
    """
    job_type = "auto_register_products"
    idempotency_key = IdempotencyManager.generate_key(job_type, "batch")
    start = time.monotonic()

    logger.info("job_started", job_type=job_type, idempotency_key=idempotency_key[:16])

    try:
        should_proceed = await _acquire_job(job_type, idempotency_key)
        if not should_proceed:
            return

        registered_count = 0
        failed_count = 0
        settings = get_settings()
        min_priority_score = 60  # 등록 임계값

        try:
            from sqlalchemy import select

            from dropagent.db.models.product import Product

            async with get_db_session() as session:
                result = await session.execute(
                    select(Product)
                    .where(Product.status == "approved")
                    .where(Product.priority_score >= min_priority_score)
                    .order_by(Product.priority_score.desc())
                    .limit(settings.app.batch_size)
                )
                products = result.scalars().all()

                for product in products:
                    try:
                        from dropagent.clients.naver.commerce_api import NaverCommerceAPI

                        naver_client = NaverCommerceAPI(settings)
                        naver_product_id = await naver_client.register_product(product)

                        product.naver_product_id = naver_product_id
                        product.status = "registered"
                        registered_count += 1

                        logger.info(
                            "product_registered",
                            ali_product_id=product.ali_product_id,
                            naver_product_id=naver_product_id,
                        )
                    except (ImportError, AttributeError):
                        logger.warning(
                            "job_client_unavailable",
                            job_type=job_type,
                            client="NaverCommerceAPI",
                        )
                        break
                    except Exception as reg_exc:
                        failed_count += 1
                        logger.warning(
                            "product_registration_failed",
                            ali_product_id=product.ali_product_id,
                            error=str(reg_exc),
                        )
        except (ImportError, AttributeError):
            logger.warning("job_dependency_unavailable", job_type=job_type)

        await _complete_job(
            idempotency_key,
            {"registered_count": registered_count, "failed_count": failed_count},
        )

        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "job_completed",
            job_type=job_type,
            registered_count=registered_count,
            failed_count=failed_count,
            duration_ms=round(duration_ms, 1),
        )
        await _log_job_run(
            job_type,
            "completed",
            duration_ms,
            {"registered_count": registered_count, "failed_count": failed_count},
        )

    except Exception as exc:
        duration_ms = (time.monotonic() - start) * 1000
        logger.error(
            "job_failed",
            job_type=job_type,
            error=str(exc),
            traceback=traceback.format_exc(),
            duration_ms=round(duration_ms, 1),
        )
        await _fail_job(idempotency_key, str(exc))
        await _log_job_run(job_type, "failed", duration_ms, error=str(exc))


async def check_orders_job() -> None:
    """
    신규 주문 확인 (5분마다 실행).

    네이버 스마트스토어의 신규 주문을 확인하고,
    알리익스프레스 자동 발주 처리를 준비합니다.
    """
    job_type = "check_orders"
    start = time.monotonic()

    logger.info("job_started", job_type=job_type)

    try:
        settings = get_settings()
        new_orders_count = 0
        processed_count = 0

        try:
            from dropagent.clients.naver.commerce_api import NaverCommerceAPI

            naver_client = NaverCommerceAPI(settings)
            new_orders = await naver_client.get_new_orders()
            new_orders_count = len(new_orders) if new_orders else 0

            if new_orders:
                for order in new_orders:
                    try:
                        async with get_db_session() as session:
                            from sqlalchemy import select

                            from dropagent.db.models.order import Order

                            # Idempotency: skip if order already exists
                            naver_order_id = order.get("order_id", "")
                            existing = await session.execute(
                                select(Order).where(Order.naver_order_id == naver_order_id)
                            )
                            if existing.scalar_one_or_none() is not None:
                                continue

                            new_order = Order(
                                naver_order_id=naver_order_id,
                                product_id=order.get("product_id", 0),
                                quantity=order.get("quantity", 1),
                                total_price=order.get("total_price", 0),
                                status="new",
                            )
                            session.add(new_order)
                            processed_count += 1
                    except Exception as order_exc:
                        logger.warning(
                            "order_processing_failed",
                            order_id=order.get("order_id"),
                            error=str(order_exc),
                        )
        except (ImportError, AttributeError):
            logger.warning("job_client_unavailable", job_type=job_type, client="NaverCommerceAPI")

        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "job_completed",
            job_type=job_type,
            new_orders_count=new_orders_count,
            processed_count=processed_count,
            duration_ms=round(duration_ms, 1),
        )
        await _log_job_run(
            job_type,
            "completed",
            duration_ms,
            {"new_orders_count": new_orders_count, "processed_count": processed_count},
        )

    except Exception as exc:
        duration_ms = (time.monotonic() - start) * 1000
        logger.error(
            "job_failed",
            job_type=job_type,
            error=str(exc),
            traceback=traceback.format_exc(),
            duration_ms=round(duration_ms, 1),
        )
        await _log_job_run(job_type, "failed", duration_ms, error=str(exc))


async def monitor_price_changes_job() -> None:
    """
    알리익스프레스 가격 변동 모니터링 (3시간마다 실행).

    등록된 상품의 가격 변동을 감지하고, 마진율이 임계값 이하로
    떨어지면 경고 로그를 남깁니다.
    """
    job_type = "monitor_price_changes"
    idempotency_key = IdempotencyManager.generate_key(job_type, "batch")
    start = time.monotonic()

    logger.info("job_started", job_type=job_type, idempotency_key=idempotency_key[:16])

    try:
        should_proceed = await _acquire_job(job_type, idempotency_key)
        if not should_proceed:
            return

        checked_count = 0
        changed_count = 0
        alert_count = 0
        margin_threshold = 10.0  # 마진율 10% 미만이면 경고

        try:
            from sqlalchemy import select

            from dropagent.db.models.product import Product

            settings = get_settings()

            async with get_db_session() as session:
                result = await session.execute(
                    select(Product).where(Product.status == "registered")
                )
                products = result.scalars().all()

                for product in products:
                    checked_count += 1
                    try:
                        from dropagent.clients.aliexpress.affiliate_api import AliExpressAffiliateAPI

                        ali_client = AliExpressAffiliateAPI(settings)
                        current_price = await ali_client.get_product_price(product.ali_product_id)

                        if current_price and product.price_ali:
                            price_diff = abs(float(current_price) - float(product.price_ali))
                            if price_diff > 0.01:
                                changed_count += 1
                                product.price_ali = current_price

                                # Record price history
                                from dropagent.db.models.price_history import PriceHistory

                                history = PriceHistory(
                                    product_id=product.id,
                                    price_ali=current_price,
                                    price_naver=product.price_naver or 0,
                                    exchange_rate=1300.00,
                                )
                                session.add(history)

                                # Check margin threshold
                                if product.margin_rate and float(product.margin_rate) < margin_threshold:
                                    alert_count += 1
                                    logger.warning(
                                        "low_margin_alert",
                                        ali_product_id=product.ali_product_id,
                                        margin_rate=float(product.margin_rate),
                                        threshold=margin_threshold,
                                    )
                    except (ImportError, AttributeError):
                        break
                    except Exception as price_exc:
                        logger.warning(
                            "price_check_failed",
                            ali_product_id=product.ali_product_id,
                            error=str(price_exc),
                        )
        except (ImportError, AttributeError):
            logger.warning("job_dependency_unavailable", job_type=job_type)

        await _complete_job(
            idempotency_key,
            {
                "checked_count": checked_count,
                "changed_count": changed_count,
                "alert_count": alert_count,
            },
        )

        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "job_completed",
            job_type=job_type,
            checked_count=checked_count,
            changed_count=changed_count,
            alert_count=alert_count,
            duration_ms=round(duration_ms, 1),
        )
        await _log_job_run(
            job_type,
            "completed",
            duration_ms,
            {"checked_count": checked_count, "changed_count": changed_count, "alert_count": alert_count},
        )

    except Exception as exc:
        duration_ms = (time.monotonic() - start) * 1000
        logger.error(
            "job_failed",
            job_type=job_type,
            error=str(exc),
            traceback=traceback.format_exc(),
            duration_ms=round(duration_ms, 1),
        )
        await _fail_job(idempotency_key, str(exc))
        await _log_job_run(job_type, "failed", duration_ms, error=str(exc))


async def health_check_job() -> None:
    """
    시스템 상태 점검 (1분마다 실행).

    DB 연결, 메모리 사용량 등을 확인합니다.
    경량 작업이므로 멱등성 키 없이 매번 실행합니다.
    """
    start = time.monotonic()

    checks: dict[str, str] = {}

    try:
        # 1. Database connectivity
        try:
            async with get_db_session() as session:
                from sqlalchemy import text

                result = await session.execute(text("SELECT 1"))
                result.scalar()
                checks["database"] = "ok"
        except Exception as db_exc:
            checks["database"] = f"error: {db_exc}"
            logger.error("health_check_db_failed", error=str(db_exc))

        # 2. Memory usage
        try:
            import resource

            mem_usage_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            mem_usage_mb = mem_usage_kb / 1024
            checks["memory_mb"] = f"{mem_usage_mb:.1f}"

            if mem_usage_mb > 512:
                logger.warning("health_check_high_memory", memory_mb=mem_usage_mb)
        except Exception:
            checks["memory_mb"] = "unavailable"

        # 3. Overall status
        all_ok = all(
            v == "ok" for k, v in checks.items() if k not in ("memory_mb",)
        )

        duration_ms = (time.monotonic() - start) * 1000

        if all_ok:
            logger.debug(
                "health_check_passed",
                checks=checks,
                duration_ms=round(duration_ms, 1),
            )
        else:
            logger.warning(
                "health_check_degraded",
                checks=checks,
                duration_ms=round(duration_ms, 1),
            )

    except Exception as exc:
        duration_ms = (time.monotonic() - start) * 1000
        logger.error(
            "health_check_error",
            error=str(exc),
            duration_ms=round(duration_ms, 1),
        )


async def daily_report_job() -> None:
    """
    일일 리포트 생성 및 발송 (매일 오전 9시 KST 실행).

    전일 기준 주요 지표를 집계하여 텔레그램으로 발송합니다:
    - 수집/등록/판매 상품 수
    - 총 매출액
    - 신규 주문 수
    """
    job_type = "daily_report"
    idempotency_key = IdempotencyManager.generate_key(job_type, "report")
    start = time.monotonic()

    logger.info("job_started", job_type=job_type, idempotency_key=idempotency_key[:16])

    try:
        should_proceed = await _acquire_job(job_type, idempotency_key)
        if not should_proceed:
            return

        # Gather metrics
        report_data: dict = {}
        try:
            from sqlalchemy import func, select

            from dropagent.db.models.order import Order
            from dropagent.db.models.product import Product

            yesterday_start = datetime.now(UTC).replace(
                hour=0, minute=0, second=0, microsecond=0,
            ) - timedelta(days=1)
            yesterday_end = yesterday_start + timedelta(days=1)

            async with get_db_session() as session:
                # Products by status
                product_result = await session.execute(
                    select(Product.status, func.count(Product.id)).group_by(Product.status)
                )
                product_counts = {row[0]: row[1] for row in product_result}

                # Orders from yesterday
                order_count_result = await session.execute(
                    select(func.count(Order.id))
                    .where(Order.created_at >= yesterday_start)
                    .where(Order.created_at < yesterday_end)
                )
                new_orders = order_count_result.scalar() or 0

                # Revenue from yesterday
                revenue_result = await session.execute(
                    select(func.sum(Order.total_price))
                    .where(Order.created_at >= yesterday_start)
                    .where(Order.created_at < yesterday_end)
                )
                total_revenue = float(revenue_result.scalar() or 0)

                report_data = {
                    "date": yesterday_start.strftime("%Y-%m-%d"),
                    "product_counts": product_counts,
                    "new_orders": new_orders,
                    "total_revenue": total_revenue,
                }
        except (ImportError, AttributeError) as gather_exc:
            logger.warning("daily_report_data_unavailable", error=str(gather_exc))
            report_data = {"error": "Data gathering partially failed"}

        # Send via Telegram
        try:
            from dropagent.clients.telegram_bot import send_telegram_message

            report_text = _format_daily_report(report_data)
            await send_telegram_message(report_text)
            logger.info("daily_report_sent")
        except (ImportError, AttributeError):
            logger.warning("job_client_unavailable", job_type=job_type, client="telegram_bot")

        await _complete_job(idempotency_key, report_data)

        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "job_completed",
            job_type=job_type,
            duration_ms=round(duration_ms, 1),
        )
        await _log_job_run(job_type, "completed", duration_ms, report_data)

    except Exception as exc:
        duration_ms = (time.monotonic() - start) * 1000
        logger.error(
            "job_failed",
            job_type=job_type,
            error=str(exc),
            traceback=traceback.format_exc(),
            duration_ms=round(duration_ms, 1),
        )
        await _fail_job(idempotency_key, str(exc))
        await _log_job_run(job_type, "failed", duration_ms, error=str(exc))


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


def _format_daily_report(data: dict) -> str:
    """일일 리포트 데이터를 텔레그램 메시지 형식으로 포맷합니다."""
    date_str = data.get("date", "N/A")
    product_counts = data.get("product_counts", {})
    new_orders = data.get("new_orders", 0)
    total_revenue = data.get("total_revenue", 0)

    lines = [
        f"[DropAgent 일일 리포트] {date_str}",
        "",
        "-- 상품 현황 --",
    ]

    for status, count in sorted(product_counts.items()):
        lines.append(f"  {status}: {count}건")

    lines.extend(
        [
            "",
            "-- 주문/매출 --",
            f"  신규 주문: {new_orders}건",
            f"  총 매출: {total_revenue:,.0f}원",
        ]
    )

    return "\n".join(lines)
