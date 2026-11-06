FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY src ./src
COPY alembic.ini entrypoint.sh ./
COPY migrations ./migrations

RUN chmod +x entrypoint.sh \
    && useradd --system --no-create-home app
USER app

EXPOSE 8000

CMD ["./entrypoint.sh"]
