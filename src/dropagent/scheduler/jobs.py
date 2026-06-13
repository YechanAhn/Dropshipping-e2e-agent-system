"""
스케줄러 작업 정의 모듈

APScheduler에 의해 주기적으로 실행되는 비동기 작업들을 정의합니다.
각 작업은 멱등성을 보장하며, 구조화된 로깅과 에러 처리를 포함합니다.

각 작업은 실제 컴포넌트(파이프라인 / 에이전트 / 클라이언트 / 리포지토리)를 직접
호출합니다. 자격증명 누락이나 외부 API 오류가 발생하면 조용히 통과하지 않고
명확한 경고 로그를 남긴 뒤 작업을 실패 처리합니다.
"""

import time
import traceback
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from dropagent.agents.order_manager import OrderManager
from dropagent.clients.aliexpress.affiliate_api import AliExpressAffiliateClient
from dropagent.clients.naver.commerce_api import NaverCommerceClient
from dropagent.clients.naver.datalab_api import NaverDataLabClient
from dropagent.clients.naver.searchad_api import NaverSearchAdClient
from dropagent.clients.naver.shopping_api import NaverShoppingClient
from dropagent.clients.telegram_bot import TelegramNotifier
from dropagent.config import get_settings
from dropagent.core.content_generator import ContentGenerator
from dropagent.core.discovery.datalab_momentum import make_datalab_momentum_provider
from dropagent.core.idempotency import IdempotencyManager
from dropagent.core.image_processor import make_image_scorer
from dropagent.core.matching import ProductMatcher
from dropagent.core.matching.vision_verifier import make_vision_verifier
from dropagent.db.repositories.analytics_repo import AnalyticsRepository
from dropagent.db.repositories.order_repo import OrderRepository
from dropagent.db.repositories.product_repo import ProductRepository
from dropagent.db.session import get_db_session
from dropagent.pipeline.discovery import DiscoveryPipeline
from dropagent.pipeline.sourcing import SourcingOrchestrator
from dropagent.utils.logging import get_logger

logger = get_logger(__name__)

# 데모드-퍼스트 디스커버리에 사용할 시드 키워드 (한국어).
# Search Ad 키워드 도구로 연관 키워드/절대 검색량을 확장하는 출발점입니다.
SEED_KEYWORDS: list[str] = [
    "무선 이어폰",
    "캠핑 용품",
    "강아지 장난감",
    "주방 정리함",
    "차량용 거치대",
    "홈트레이닝 기구",
    "휴대용 선풍기",
    "골프 용품",
]

# 알리익스프레스 핫상품 수집 대상 카테고리 ID (수집은 modest 하게 유지).
ALI_HOT_CATEGORY_IDS: list[str] = ["7", "1501", "200000343"]

# 가격 모니터링 1회 실행 시 표본으로 잡을 등록 상품 수 상한.
PRICE_MONITOR_SAMPLE_SIZE = 20

# 자동 등록 임계값 (priority_score). 이 점수 이상 + status 'approved' 만 등록.
MIN_REGISTER_PRIORITY_SCORE = 60.0

# 알리 -> 원화 환산에 사용하는 기본 환율 (가격 기록용).
DEFAULT_FX_RATE = Decimal("1350")

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
    알리익스프레스 핫상품 수집 (6시간마다 실행).

    실제 ``AliExpressAffiliateClient.get_hot_products`` 를 사용하여 몇 개의 트렌드
    카테고리에서 인기 상품을 조회하고 수집 건수를 로깅합니다. 멱등성 키로 중복
    수집을 방지합니다.
    """
    job_type = "collect_ali_products"
    idempotency_key = IdempotencyManager.generate_key(job_type, "batch")
    start = time.monotonic()

    logger.info("job_started", job_type=job_type, idempotency_key=idempotency_key[:16])

    try:
        should_proceed = await _acquire_job(job_type, idempotency_key)
        if not should_proceed:
            return

        settings = get_settings()
        collected_count = 0

        ali_client = AliExpressAffiliateClient(settings.aliexpress)
        try:
            for category_id in ALI_HOT_CATEGORY_IDS:
                try:
                    result = await ali_client.get_hot_products(category_id, page=1)
                except Exception as cat_exc:
                    logger.warning(
                        "ali_hot_products_failed",
                        job_type=job_type,
                        category_id=category_id,
                        error=str(cat_exc),
                    )
                    continue
                count = len(result.products)
                collected_count += count
                logger.info(
                    "ali_hot_products_collected",
                    category_id=category_id,
                    count=count,
                    total_record_count=result.total_count,
                )
        finally:
            await ali_client.close()

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
    네이버 수요 기반 트렌드 수집 (12시간마다 실행).

    ``DiscoveryPipeline`` (Search Ad 수요 확장 + Shopping 공급/경쟁 측정)을
    시드 키워드에 대해 실행하고, 각 기회 키워드를 ``AnalyticsRepository`` 의
    trend_data 로 영속화합니다.
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

        searchad_client = NaverSearchAdClient(settings.searchad)
        shopping_client = NaverShoppingClient(settings.naver)
        datalab_client = NaverDataLabClient(settings.naver)
        momentum_provider = make_datalab_momentum_provider(datalab_client)
        try:
            pipeline = DiscoveryPipeline(
                searchad_client,
                shopping_client,
                momentum_provider=momentum_provider,
            )
            candidates = await pipeline.discover(SEED_KEYWORDS, top_n=30)
            logger.info("discovery_candidates", job_type=job_type, count=len(candidates))

            async with get_db_session() as session:
                analytics_repo = AnalyticsRepository(session)
                for cand in candidates:
                    try:
                        await analytics_repo.add_trend_data(
                            {
                                "keyword": cand.keyword,
                                "category": cand.grade_ko,
                                "click_ratio": Decimal(str(round(cand.catalog_ratio * 100, 2))),
                                "search_volume": int(cand.monthly_volume),
                            }
                        )
                        trend_count += 1
                    except Exception as persist_exc:
                        logger.warning(
                            "trend_persist_failed",
                            keyword=cand.keyword,
                            error=str(persist_exc),
                        )
        finally:
            await searchad_client.close()
            await shopping_client.close()
            await datalab_client.close()

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
    저장된 상품의 우선순위 스코어 갱신 (6시간마다 실행).

    이미 산출되어 저장된 마진/수요/리스크/운영비용 지표를 기반으로
    ``PriorityScorer`` 로 priority_score 를 재계산하고 저장합니다.
    """
    job_type = "update_scores"
    idempotency_key = IdempotencyManager.generate_key(job_type, "batch")
    start = time.monotonic()

    logger.info("job_started", job_type=job_type, idempotency_key=idempotency_key[:16])

    try:
        should_proceed = await _acquire_job(job_type, idempotency_key)
        if not should_proceed:
            return

        from dropagent.core.priority_scorer import PriorityScorer

        scorer = PriorityScorer()
        updated_count = 0

        async with get_db_session() as session:
            product_repo = ProductRepository(session)
            products = await product_repo.list_all(limit=500)

            for product in products:
                if product.status not in ("pending", "approved", "registered"):
                    continue
                try:
                    margin = min(max(float(product.margin_rate or 0) / 100.0, 0.0), 1.0)
                    demand = min(max(float(product.demand_score or 0), 0.0), 1.0)
                    risk = min(max(float(product.risk_score or 0), 0.0), 1.0)
                    ops_cost = min(max(float(product.ops_cost_score or 0), 0.0), 1.0)
                    supplier = 0.5  # default supplier confidence

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

    status 가 'approved' 이고 priority_score 가 임계값 이상인 상품에 대해
    ``SourcingOrchestrator`` 로 리스팅을 평가하고, 결과가 'ready' 인 경우에만
    ``NaverCommerceClient.register_product`` 로 등록합니다. HITL 정책을 존중하여
    이미 승인된 상품에만 작용합니다.
    """
    job_type = "auto_register_products"
    idempotency_key = IdempotencyManager.generate_key(job_type, "batch")
    start = time.monotonic()

    logger.info("job_started", job_type=job_type, idempotency_key=idempotency_key[:16])

    try:
        should_proceed = await _acquire_job(job_type, idempotency_key)
        if not should_proceed:
            return

        settings = get_settings()
        registered_count = 0
        skipped_count = 0
        failed_count = 0

        ali_client = AliExpressAffiliateClient(settings.aliexpress)
        commerce_client = NaverCommerceClient(settings.naver)
        try:
            # Image scorer (dHash) cheaply re-ranks candidates by photo; the
            # multimodal verifier (local Gemma via Ollama) then confirms same-SKU
            # identity. Both fail safe -> human review, never crash the job.
            matcher = ProductMatcher(
                ali_client,
                image_scorer=make_image_scorer(),
                verifier=make_vision_verifier(),
            )
            content_generator = ContentGenerator()
            orchestrator = SourcingOrchestrator(matcher, content_generator)

            async with get_db_session() as session:
                product_repo = ProductRepository(session)
                approved = await product_repo.list_all(
                    status="approved", limit=settings.app.batch_size
                )

                for product in approved:
                    score = float(product.priority_score or 0)
                    if score < MIN_REGISTER_PRIORITY_SCORE:
                        skipped_count += 1
                        continue

                    from dropagent.pipeline.discovery import DiscoveryCandidate

                    candidate = DiscoveryCandidate(
                        keyword=product.product_name_ko or product.product_name_en or "",
                        monthly_volume=0,
                        price_median=int(product.price_naver or 0),
                    )
                    try:
                        sourcing = await orchestrator.evaluate_candidate(candidate)
                    except Exception as eval_exc:
                        failed_count += 1
                        logger.warning(
                            "sourcing_evaluation_failed",
                            product_id=product.id,
                            ali_product_id=product.ali_product_id,
                            error=str(eval_exc),
                        )
                        continue

                    if sourcing.status != "ready" or sourcing.register_payload is None:
                        skipped_count += 1
                        logger.info(
                            "auto_register_skipped",
                            product_id=product.id,
                            status=sourcing.status,
                            notes=sourcing.notes,
                        )
                        continue

                    try:
                        naver_product_id = await commerce_client.register_product(
                            sourcing.register_payload
                        )
                        await product_repo.update(
                            product.id,
                            {
                                "naver_product_id": naver_product_id,
                                "status": "registered",
                            },
                        )
                        registered_count += 1
                        logger.info(
                            "product_registered",
                            ali_product_id=product.ali_product_id,
                            naver_product_id=naver_product_id,
                        )
                    except Exception as reg_exc:
                        failed_count += 1
                        logger.warning(
                            "product_registration_failed",
                            ali_product_id=product.ali_product_id,
                            error=str(reg_exc),
                        )
        finally:
            await ali_client.close()
            await commerce_client.close()

        result = {
            "registered_count": registered_count,
            "skipped_count": skipped_count,
            "failed_count": failed_count,
        }
        await _complete_job(idempotency_key, result)

        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "job_completed",
            job_type=job_type,
            duration_ms=round(duration_ms, 1),
            **result,
        )
        await _log_job_run(job_type, "completed", duration_ms, result)

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

    ``OrderManager.poll_new_orders`` 로 네이버 스마트스토어의 결제 완료 주문을
    확인/영속화하고, 신규 주문이 있으면 텔레그램으로 알립니다. poll_new_orders 가
    자체적으로 멱등하므로(naver_order_id 중복 skip) 별도 멱등성 키는 두지 않습니다.
    """
    job_type = "check_orders"
    start = time.monotonic()

    logger.info("job_started", job_type=job_type)

    try:
        settings = get_settings()
        new_orders_count = 0

        commerce_client = NaverCommerceClient(settings.naver)
        try:
            async with get_db_session() as session:
                order_repo = OrderRepository(session)
                product_repo = ProductRepository(session)
                manager = OrderManager(order_repo, product_repo, commerce_client)
                created = await manager.poll_new_orders()
                new_orders_count = len(created)
        finally:
            await commerce_client.close()

        if new_orders_count > 0:
            try:
                notifier = TelegramNotifier(settings.telegram)
                await notifier.send_message(
                    f"[DropAgent] 신규 주문 {new_orders_count}건이 접수되었습니다."
                )
            except Exception as notify_exc:
                logger.warning(
                    "order_notification_failed",
                    job_type=job_type,
                    error=str(notify_exc),
                )

        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "job_completed",
            job_type=job_type,
            new_orders_count=new_orders_count,
            duration_ms=round(duration_ms, 1),
        )
        await _log_job_run(
            job_type,
            "completed",
            duration_ms,
            {"new_orders_count": new_orders_count},
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

    등록된 상품을 표본으로 잡아 ``AliExpressAffiliateClient.get_product_detail`` 로
    현재 가격을 조회하고, 변동을 ``AnalyticsRepository.add_price_record`` 로
    기록합니다.
    """
    job_type = "monitor_price_changes"
    idempotency_key = IdempotencyManager.generate_key(job_type, "batch")
    start = time.monotonic()

    logger.info("job_started", job_type=job_type, idempotency_key=idempotency_key[:16])

    try:
        should_proceed = await _acquire_job(job_type, idempotency_key)
        if not should_proceed:
            return

        settings = get_settings()
        checked_count = 0
        changed_count = 0

        ali_client = AliExpressAffiliateClient(settings.aliexpress)
        try:
            async with get_db_session() as session:
                product_repo = ProductRepository(session)
                analytics_repo = AnalyticsRepository(session)

                products = await product_repo.list_all(
                    status="registered", limit=PRICE_MONITOR_SAMPLE_SIZE
                )
                by_ali_id = {
                    p.ali_product_id: p for p in products if p.ali_product_id
                }
                if by_ali_id:
                    try:
                        details = await ali_client.get_product_detail(list(by_ali_id.keys()))
                    except Exception as detail_exc:
                        logger.warning(
                            "ali_product_detail_failed",
                            job_type=job_type,
                            error=str(detail_exc),
                        )
                        details = []

                    for detail in details:
                        product = by_ali_id.get(detail.product_id)
                        if product is None:
                            continue
                        checked_count += 1
                        current_price = detail.price.sale_price
                        previous_price = product.price_ali
                        if previous_price is None or current_price != previous_price:
                            changed_count += 1
                        try:
                            await analytics_repo.add_price_record(
                                product_id=product.id,
                                price_ali=current_price,
                                price_naver=product.price_naver or Decimal("0"),
                                exchange_rate=DEFAULT_FX_RATE,
                            )
                            product.price_ali = current_price
                        except Exception as record_exc:
                            logger.warning(
                                "price_record_failed",
                                ali_product_id=product.ali_product_id,
                                error=str(record_exc),
                            )
        finally:
            await ali_client.close()

        result = {"checked_count": checked_count, "changed_count": changed_count}
        await _complete_job(idempotency_key, result)

        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "job_completed",
            job_type=job_type,
            duration_ms=round(duration_ms, 1),
            **result,
        )
        await _log_job_run(job_type, "completed", duration_ms, result)

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

    DB 연결(SELECT 1)과 메모리 사용량을 확인합니다.
    경량 작업이므로 멱등성 키 없이 매번 실행합니다.
    """
    start = time.monotonic()

    checks: dict[str, str] = {}

    try:
        # 1. Database connectivity (lightweight SELECT 1 ping)
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

    상품 현황 / 주문·매출 요약을 집계하여 ``TelegramNotifier`` 로 발송합니다:
    - 상태별 상품 수 (ProductRepository.count_by_status 대용: list 기반 집계)
    - 매출 요약 (OrderRepository.get_revenue_summary)
    - 상태별 주문 수 (OrderRepository.count_by_status)
    """
    job_type = "daily_report"
    idempotency_key = IdempotencyManager.generate_key(job_type, "report")
    start = time.monotonic()

    logger.info("job_started", job_type=job_type, idempotency_key=idempotency_key[:16])

    try:
        should_proceed = await _acquire_job(job_type, idempotency_key)
        if not should_proceed:
            return

        settings = get_settings()

        async with get_db_session() as session:
            order_repo = OrderRepository(session)
            product_repo = ProductRepository(session)

            revenue = await order_repo.get_revenue_summary(days=1)
            order_status_counts = await order_repo.count_by_status()
            registered = await product_repo.count(status="registered")
            approved = await product_repo.count(status="approved")

        report_data = {
            "date": (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d"),
            "products_registered": registered,
            "products_approved": approved,
            "order_status_counts": order_status_counts,
            "total_revenue": revenue.get("total_revenue", 0.0),
            "total_orders": revenue.get("total_orders", 0),
        }

        report_text = _format_daily_report(report_data)
        try:
            notifier = TelegramNotifier(settings.telegram)
            sent = await notifier.send_message(report_text)
            logger.info("daily_report_sent", success=sent)
        except Exception as notify_exc:
            logger.warning(
                "daily_report_send_failed",
                job_type=job_type,
                error=str(notify_exc),
            )

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
    registered = data.get("products_registered", 0)
    approved = data.get("products_approved", 0)
    order_status_counts = data.get("order_status_counts", {})
    total_orders = data.get("total_orders", 0)
    total_revenue = data.get("total_revenue", 0)

    lines = [
        f"[DropAgent 일일 리포트] {date_str}",
        "",
        "-- 상품 현황 --",
        f"  승인 대기/완료(approved): {approved}건",
        f"  등록 완료(registered): {registered}건",
        "",
        "-- 주문/매출 --",
        f"  신규 주문(24h): {total_orders}건",
        f"  총 매출(24h): {total_revenue:,.0f}원",
    ]

    if order_status_counts:
        lines.append("")
        lines.append("-- 주문 상태별 --")
        for status, count in sorted(order_status_counts.items()):
            lines.append(f"  {status}: {count}건")

    return "\n".join(lines)
