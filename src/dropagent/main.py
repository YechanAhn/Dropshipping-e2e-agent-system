"""
DropAgent - Dropshipping E2E Agent System
Main application entrypoint

알리익스프레스 → 네이버 스마트스토어 드롭쉬핑 자동화 시스템의
메인 진입점입니다. DB 초기화, 스케줄러 구동, FastAPI 서버 구동, 시그널
처리를 담당합니다.
"""

import asyncio
import signal
import sys

import uvicorn

from dropagent.api.app import create_app
from dropagent.config import get_settings
from dropagent.db.session import close_db, init_db
from dropagent.scheduler.runner import SchedulerRunner
from dropagent.utils.logging import get_logger, setup_logging


async def main() -> None:
    """
    메인 애플리케이션 시작점.

    순서:
    1. 설정 로드 및 로깅 초기화
    2. 데이터베이스 초기화
    3. 스케줄러 구성 및 시작
    4. FastAPI(uvicorn) 서버를 asyncio 태스크로 동시 구동
    5. 종료 시그널 대기 (SIGINT, SIGTERM)
    6. 정상 종료 처리 (서버 + 스케줄러 + DB)
    """
    # 1. Load settings and setup logging
    settings = get_settings()
    setup_logging(
        log_level=settings.app.log_level,
        environment=settings.app.environment,
    )

    logger = get_logger(__name__)
    logger.info(
        "application_starting",
        environment=settings.app.environment,
        log_level=settings.app.log_level,
        debug=settings.app.debug,
    )

    scheduler: SchedulerRunner | None = None
    api_server: uvicorn.Server | None = None
    api_task: asyncio.Task[None] | None = None
    shutdown_event = asyncio.Event()

    # Signal handler
    def _handle_signal(sig: signal.Signals) -> None:
        sig_name = sig.name
        logger.info("shutdown_signal_received", signal=sig_name)
        shutdown_event.set()

    # Register signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal, sig)

    try:
        # 2. Initialize database
        logger.info("database_initializing")
        await init_db()
        logger.info("database_initialized")

        # 3. Configure and start scheduler
        scheduler = SchedulerRunner()
        scheduler.configure_jobs()

        logger.info("scheduler_starting")
        await scheduler.start()
        logger.info(
            "scheduler_started",
            jobs=len(scheduler.get_job_status()),
        )

        # 4. Start the FastAPI app under uvicorn as a concurrent task.
        #    ``install_signal_handlers=False`` keeps our own signal handlers in
        #    charge of graceful shutdown.
        api_config = uvicorn.Config(
            create_app(),
            host=settings.app.api_host,
            port=settings.app.api_port,
            log_level=settings.app.log_level.lower(),
            install_signal_handlers=False,
        )
        api_server = uvicorn.Server(api_config)
        api_task = asyncio.create_task(api_server.serve())
        logger.info(
            "api_server_started",
            host=settings.app.api_host,
            port=settings.app.api_port,
        )

        logger.info("application_ready")

        # 5. Wait for shutdown signal (or the API server exiting on its own).
        wait_shutdown = asyncio.ensure_future(shutdown_event.wait())
        await asyncio.wait(
            {wait_shutdown, api_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not wait_shutdown.done():
            wait_shutdown.cancel()

    except Exception as exc:
        logger.error(
            "application_startup_error",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise

    finally:
        # 6. Graceful shutdown
        logger.info("application_shutting_down")

        if api_server is not None:
            logger.info("api_server_stopping")
            api_server.should_exit = True
            if api_task is not None:
                try:
                    await api_task
                except asyncio.CancelledError:
                    pass
            logger.info("api_server_stopped")

        if scheduler is not None and scheduler.is_running:
            logger.info("scheduler_stopping")
            await scheduler.stop()
            logger.info("scheduler_stopped")

        logger.info("database_closing")
        await close_db()
        logger.info("database_closed")

        logger.info("application_stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"Fatal error: {exc}", file=sys.stderr)
        sys.exit(1)
