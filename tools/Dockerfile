FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY mock_helpdesk ./mock_helpdesk
COPY simulator ./simulator

RUN useradd --system --no-create-home app
USER app

EXPOSE 8000

CMD ["uvicorn", "mock_helpdesk.app:app", "--host", "0.0.0.0", "--port", "8000"]
