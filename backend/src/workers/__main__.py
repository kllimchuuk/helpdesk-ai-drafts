import asyncio
import logging
import signal
import sys
from typing import TextIO

from config import settings
from workers.runner import run_worker

logger = logging.getLogger("workers")

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
TICKET_FIELDS = ("event_id", "ticket_id", "attempt")


class TicketContextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        context = " ".join(
            f"{field}={getattr(record, field)}"
            for field in TICKET_FIELDS
            if hasattr(record, field)
        )
        if not context:
            return line
        message, newline, traceback = line.partition("\n")
        return f"{message} {context}{newline}{traceback}"


def configure_logging(stream: TextIO = sys.stderr) -> logging.Handler:
    handler = logging.StreamHandler(stream)
    handler.setFormatter(TicketContextFormatter(LOG_FORMAT))
    return handler


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
