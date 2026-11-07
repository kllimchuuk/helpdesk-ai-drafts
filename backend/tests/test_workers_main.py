import io
import logging

from workers.__main__ import configure_logging


def capture() -> tuple[logging.Logger, io.StringIO]:
    stream = io.StringIO()
    logger = logging.getLogger("test.workers.main")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(configure_logging(stream))
    return logger, stream


def test_ticket_lines_carry_the_ticket_identity() -> None:
    logger, stream = capture()

    logger.info(
        "Lease lost", extra={"event_id": "evt_1", "ticket_id": "T-1", "attempt": 2}
    )

    assert (
        stream.getvalue()
        .rstrip()
        .endswith("Lease lost event_id=evt_1 ticket_id=T-1 attempt=2")
    )


def test_other_lines_are_printed_without_ticket_fields() -> None:
    logger, stream = capture()

    logger.info("Worker started")

    assert stream.getvalue().rstrip().endswith("Worker started")
