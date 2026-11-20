import io
import json
import logging

from fastapi import FastAPI

from config import Settings
from core.logging import SERVER_LOGGERS, JsonFormatter, build_log_handler
from main import create_app, lifespan


def capture(log_format: str) -> tuple[logging.Logger, io.StringIO]:
    stream = io.StringIO()
    logger = logging.getLogger(f"test.logging.{log_format}")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(build_log_handler(log_format, stream))
    return logger, stream


def test_a_json_line_carries_the_ticket_identity_as_fields() -> None:
    logger, stream = capture("json")

    logger.warning(
        "Lease lost", extra={"event_id": "evt_1", "ticket_id": "T-1", "attempt": 2}
    )

    line = json.loads(stream.getvalue())
    assert line["message"] == "Lease lost"
    assert line["level"] == "WARNING"
    assert line["logger"] == "test.logging.json"
    assert line["event_id"] == "evt_1"
    assert line["ticket_id"] == "T-1"
    assert line["attempt"] == 2
    assert "time" in line


def test_a_json_line_without_a_ticket_has_no_ticket_fields() -> None:
    logger, stream = capture("json")

    logger.info("Worker started")

    line = json.loads(stream.getvalue())
    assert "event_id" not in line
    assert "ticket_id" not in line


def test_an_exception_stays_inside_one_json_line() -> None:
    logger, stream = capture("json")

    try:
        raise ValueError("bad")
    except ValueError:
        logger.exception("Result write failed")

    assert len(stream.getvalue().splitlines()) == 1
    assert "ValueError: bad" in json.loads(stream.getvalue())["exception"]


def test_the_text_format_keeps_the_key_value_suffix() -> None:
    logger, stream = capture("text")

    logger.info("Lease lost", extra={"event_id": "evt_1", "ticket_id": "T-1"})

    assert (
        stream.getvalue().rstrip().endswith("Lease lost event_id=evt_1 ticket_id=T-1")
    )


def make_app(log_format: str) -> FastAPI:
    return create_app(Settings(_env_file=None, LOG_FORMAT=log_format))


async def test_the_backend_json_format_covers_the_server_loggers() -> None:
    app = make_app("json")
    before = {name: list(logging.getLogger(name).handlers) for name in SERVER_LOGGERS}

    async with lifespan(app):
        for name in SERVER_LOGGERS:
            handlers = logging.getLogger(name).handlers
            assert handlers
            assert all(isinstance(h.formatter, JsonFormatter) for h in handlers)
        assert logging.getLogger().level == logging.INFO

    assert {
        name: list(logging.getLogger(name).handlers) for name in SERVER_LOGGERS
    } == before


async def test_an_access_line_is_one_json_object() -> None:
    app = make_app("json")
    stream = io.StringIO()

    async with lifespan(app):
        for handler in logging.getLogger("uvicorn.access").handlers:
            handler.setStream(stream)
        logging.getLogger("uvicorn.access").info(
            '%s - "%s %s HTTP/%s" %d',
            "172.18.0.1:5000",
            "POST",
            "/webhooks/helpdesk",
            "1.1",
            200,
        )

    line = json.loads(stream.getvalue())
    assert line["logger"] == "uvicorn.access"
    assert "POST /webhooks/helpdesk" in line["message"]


async def test_the_text_format_leaves_the_server_loggers_alone() -> None:
    app = make_app("text")
    before = list(logging.getLogger("uvicorn.access").handlers)

    async with lifespan(app):
        assert logging.getLogger("uvicorn.access").handlers == before
