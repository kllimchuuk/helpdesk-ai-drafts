import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config import Settings, settings
from core.exceptions import AppException
from health.router import router as health_router

logger = logging.getLogger(__name__)


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

    app = FastAPI(title="Helpdesk AI Drafts")
    app.state.settings = app_settings

    app.add_exception_handler(AppException, domain_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    app.include_router(health_router)

    return app


app = create_app()
