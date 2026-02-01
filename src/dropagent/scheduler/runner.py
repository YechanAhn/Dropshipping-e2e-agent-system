"""
APScheduler 실행기 모듈

모든 스케줄 작업을 AsyncIOScheduler에 등록하고 관리합니다.
타임존은 Asia/Seoul (KST)을 사용합니다.
"""

from typing import Any

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, JobExecutionEvent
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from dropagent.utils.logging import get_logger

from .jobs import (
    auto_register_products_job,
    check_orders_job,
    collect_ali_products_job,
    collect_naver_trends_job,
    daily_report_job,
    health_check_job,
    monitor_price_changes_job,
    update_scores_job,
)

logger = get_logger(__name__)


class SchedulerRunner:
    """
    APScheduler 기반 작업 실행기.

    모든 주기적 작업을 등록하고, 시작/중지를 관리합니다.
    타임존은 KST(Asia/Seoul)를 사용하며, 각 작업은 coalesce=True로
    밀린 작업을 합쳐서 실행합니다.

    Examples:
        >>> runner = SchedulerRunner()
        >>> runner.configure_jobs()
        >>> await runner.start()
        >>> # ... application runs ...
        >>> await runner.stop()
    """

    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler(
            timezone="Asia/Seoul",
            job_defaults={
                "coalesce": True,          # 밀린 작업은 1회만 실행
                "max_instances": 1,         # 동일 작업 동시 실행 방지
                "misfire_grace_time": 300,  # 5분까지는 밀려도 실행
            },
        )
        self._is_running = False

        # Register event listeners for monitoring
        self.scheduler.add_listener(self._on_job_executed, EVENT_JOB_EXECUTED)
        self.scheduler.add_listener(self._on_job_error, EVENT_JOB_ERROR)

        logger.info("scheduler_runner_initialized")

    # ------------------------------------------------------------------
    # Job configuration
    # ------------------------------------------------------------------

    def configure_jobs(self) -> None:
        """
        모든 스케줄 작업을 등록합니다.

        각 작업의 실행 주기는 PRD v2에 정의된 값을 따릅니다:
        - 상품 수집: 6시간
        - 네이버 트렌드: 12시간
        - 스코어 갱신: 6시간
        - 자동 등록: 1시간
        - 주문 확인: 5분
        - 가격 모니터링: 3시간
        - 헬스체크: 1분
        - 일일 리포트: 매일 09:00 KST
        """
        # 상품 수집 (6시간마다)
        self.scheduler.add_job(
            collect_ali_products_job,
            trigger=IntervalTrigger(hours=6),
            id="collect_ali_products",
            name="AliExpress 상품 수집",
            replace_existing=True,
        )

        # 네이버 트렌드 수집 (12시간마다)
        self.scheduler.add_job(
            collect_naver_trends_job,
            trigger=IntervalTrigger(hours=12),
            id="collect_naver_trends",
            name="네이버 트렌드 수집",
            replace_existing=True,
        )

        # 스코어 갱신 (6시간마다)
        self.scheduler.add_job(
            update_scores_job,
            trigger=IntervalTrigger(hours=6),
            id="update_scores",
            name="우선순위 스코어 재계산",
            replace_existing=True,
        )

        # 자동 등록 (1시간마다)
        self.scheduler.add_job(
            auto_register_products_job,
            trigger=IntervalTrigger(hours=1),
            id="auto_register_products",
            name="상품 자동 등록",
            replace_existing=True,
        )

        # 주문 확인 (5분마다)
        self.scheduler.add_job(
            check_orders_job,
            trigger=IntervalTrigger(minutes=5),
            id="check_orders",
            name="신규 주문 확인",
            replace_existing=True,
        )

        # 가격 모니터링 (3시간마다)
        self.scheduler.add_job(
            monitor_price_changes_job,
            trigger=IntervalTrigger(hours=3),
            id="monitor_price_changes",
            name="가격 변동 모니터링",
            replace_existing=True,
        )

        # 헬스 체크 (1분마다)
        self.scheduler.add_job(
            health_check_job,
            trigger=IntervalTrigger(minutes=1),
            id="health_check",
            name="시스템 상태 점검",
            replace_existing=True,
        )

        # 일일 리포트 (매일 09:00 KST)
        self.scheduler.add_job(
            daily_report_job,
            trigger=CronTrigger(hour=9, minute=0, timezone="Asia/Seoul"),
            id="daily_report",
            name="일일 리포트 발송",
            replace_existing=True,
        )

        job_count = len(self.scheduler.get_jobs())
        logger.info("scheduler_jobs_configured", job_count=job_count)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """
        스케줄러를 시작합니다.

        configure_jobs()를 먼저 호출해야 합니다.
        이미 실행 중이면 경고 로그만 남기고 반환합니다.
        """
        if self._is_running:
            logger.warning("scheduler_already_running")
            return

        if not self.scheduler.get_jobs():
            logger.warning("scheduler_no_jobs_configured")

        self.scheduler.start()
        self._is_running = True

        logger.info(
            "scheduler_started",
            job_count=len(self.scheduler.get_jobs()),
        )

    async def stop(self) -> None:
        """
        스케줄러를 정상적으로 종료합니다.

        실행 중인 작업이 완료될 때까지 대기합니다.
        """
        if not self._is_running:
            logger.warning("scheduler_not_running")
            return

        self.scheduler.shutdown(wait=True)
        self._is_running = False

        logger.info("scheduler_stopped")

    # ------------------------------------------------------------------
    # Status and monitoring
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """스케줄러 실행 여부."""
        return self._is_running

    @staticmethod
    def _safe_next_run_time(job: Any) -> str | None:
        """next_run_time을 안전하게 읽어 ISO 문자열로 반환합니다.

        APScheduler 3.x에서 스케줄러 시작 전에는 next_run_time 슬롯이
        설정되지 않으므로 hasattr 가드가 필요합니다.
        """
        if hasattr(job, "next_run_time") and job.next_run_time is not None:
            return job.next_run_time.isoformat()
        return None

    def get_job_status(self) -> list[dict[str, Any]]:
        """
        등록된 모든 작업의 상태를 반환합니다.

        Returns:
            작업 정보 딕셔너리 리스트. 각 항목은 id, name,
            next_run_time, trigger 정보를 포함합니다.
        """
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": self._safe_next_run_time(job),
                    "trigger": str(job.trigger),
                    "pending": job.pending,
                }
            )
        return jobs

    def get_job_by_id(self, job_id: str) -> dict[str, Any] | None:
        """특정 작업의 상태를 반환합니다."""
        job = self.scheduler.get_job(job_id)
        if job is None:
            return None

        return {
            "id": job.id,
            "name": job.name,
            "next_run_time": self._safe_next_run_time(job),
            "trigger": str(job.trigger),
            "pending": job.pending,
        }

    def pause_job(self, job_id: str) -> None:
        """특정 작업을 일시 중지합니다."""
        self.scheduler.pause_job(job_id)
        logger.info("scheduler_job_paused", job_id=job_id)

    def resume_job(self, job_id: str) -> None:
        """일시 중지된 작업을 재개합니다."""
        self.scheduler.resume_job(job_id)
        logger.info("scheduler_job_resumed", job_id=job_id)

    # ------------------------------------------------------------------
    # Event listeners
    # ------------------------------------------------------------------

    @staticmethod
    def _on_job_executed(event: JobExecutionEvent) -> None:
        """작업 실행 완료 이벤트 핸들러."""
        run_time = getattr(event, "scheduled_run_time", None)
        logger.debug(
            "scheduler_job_executed",
            job_id=event.job_id,
            scheduled_run_time=run_time.isoformat() if run_time else None,
        )

    @staticmethod
    def _on_job_error(event: JobExecutionEvent) -> None:
        """작업 실행 에러 이벤트 핸들러."""
        run_time = getattr(event, "scheduled_run_time", None)
        logger.error(
            "scheduler_job_error",
            job_id=event.job_id,
            exception=str(event.exception) if event.exception else None,
            scheduled_run_time=run_time.isoformat() if run_time else None,
        )
