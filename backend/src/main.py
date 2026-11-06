import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config import Settings, settings
from core.database import build_engine, build_session_factory
from core.exceptions import AppException
from health.router import router as health_router
from tickets.router import router as tickets_router
from webhooks.router import router as webhooks_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        await app.state.db_engine.dispose()


async def domain_exception_handler(
    _request: Request, exc: AppException
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.code,
            "message": exc.message,
            "payload": exc.payload,
        },
    )


async def unhandled_exception_handler(
    _request: Request, exc: Exception
) -> JSONResponse:
    logger.exception("Unhandled error", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "code": "internal_error",
            "message": "Internal server error",
            "payload": {},
        },
    )


def create_app(app_settings: Settings | None = None) -> FastAPI:
    app_settings = app_settings or settings

    app = FastAPI(title="Helpdesk AI Drafts", lifespan=lifespan)
    app.state.settings = app_settings
    app.state.db_engine = build_engine(app_settings.DATABASE_URL)
    app.state.session_factory = build_session_factory(app.state.db_engine)

    app.add_exception_handler(AppException, domain_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    app.include_router(health_router)
    app.include_router(webhooks_router)
    app.include_router(tickets_router)

    return app


app = create_app()
