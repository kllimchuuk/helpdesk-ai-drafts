import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TextIO

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
TICKET_FIELDS = ("event_id", "ticket_id", "attempt")
SERVER_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


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


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in TICKET_FIELDS:
            if hasattr(record, field):
                line[field] = getattr(record, field)
        if record.exc_info:
            line["exception"] = self.formatException(record.exc_info)
        return json.dumps(line, ensure_ascii=False)


def build_log_handler(log_format: str, stream: TextIO = sys.stderr) -> logging.Handler:
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        JsonFormatter() if log_format == "json" else TicketContextFormatter(LOG_FORMAT)
    )
    return handler


@contextmanager
def installed_log_handler(log_format: str) -> Iterator[logging.Handler]:
    handler = build_log_handler(log_format)
    root = logging.getLogger()
    root_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    replaced = []
    if log_format == "json":
        for name in SERVER_LOGGERS:
            server = logging.getLogger(name)
            replaced.append((server, list(server.handlers), server.propagate))
            server.handlers = [handler]
            server.propagate = False
    try:
        yield handler
    finally:
        for server, handlers, propagate in replaced:
            server.handlers = handlers
            server.propagate = propagate
        root.setLevel(root_level)
        root.removeHandler(handler)
