import asyncio
import logging
import signal

from config import settings
from workers.runner import run_worker

logger = logging.getLogger("workers")


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    logger.info("Worker started")
    await run_worker(settings, stop)
    logger.info("Worker stopped")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    asyncio.run(main())
