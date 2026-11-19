import asyncio
import logging
import signal
import sys
from typing import TextIO

from config import settings
from core.logging import build_log_handler
from workers.runner import run_worker

logger = logging.getLogger("workers")


def configure_logging(
    stream: TextIO = sys.stderr, log_format: str = settings.LOG_FORMAT
) -> logging.Handler:
    return build_log_handler(log_format, stream)


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    logger.info("Worker started")
    await run_worker(settings, stop)
    logger.info("Worker stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, handlers=[configure_logging()])
    asyncio.run(main())
