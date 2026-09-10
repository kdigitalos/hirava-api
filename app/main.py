"""ASGI entry point: uvicorn app.main:app --reload."""

import logging
import threading
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm.exc import StaleDataError

from app.api.v1.router import api_router
from app.core.config import Settings
from app.data import registry  # noqa: F401
from app.data.database import build_engine, session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = build_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(application):
        yield
        engine.dispose()

    application = FastAPI(
        title="Hirava API",
        description="Unified Core, RMS, and HRMS API. Human approval is required for employment transitions.",
        version="0.2.0", lifespan=lifespan,
        docs_url="/docs" if settings.expose_docs else None,
        redoc_url="/redoc" if settings.expose_docs else None,
        openapi_url="/openapi.json" if settings.expose_docs else None,
    )
    application.state.settings = settings
    application.state.engine = engine
    application.state.sessions = session_factory(engine)
    application.state.login_attempts = {}
    application.state.login_lock = threading.Lock()
    application.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                               allow_methods=["GET", "POST", "PATCH", "DELETE"],
                               allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
                               expose_headers=["X-Request-ID"])

    @application.middleware("http")
    async def correlation(request: Request, call_next):
        request.state.correlation_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.correlation_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(IntegrityError)
    async def integrity_error(request, exc):
        return JSONResponse(status_code=409, content={"detail": "Duplicate record or conflicting relationship"})

    @application.exception_handler(StaleDataError)
    async def stale_error(request, exc):
        return JSONResponse(status_code=409, content={"detail": "Record changed concurrently; reload and retry"})

    @application.exception_handler(OperationalError)
    async def database_error(request, exc):
        logging.getLogger(__name__).error("Database operation failed, request=%s", request.state.correlation_id)
        return JSONResponse(status_code=503, content={"detail": "Database unavailable or busy; retry later"})

    application.include_router(api_router, prefix="/api/v1")
    return application


app = create_app()
