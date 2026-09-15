"""ASGI entry point: uvicorn app.main:app --reload."""

import logging
import asyncio
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
        stop = asyncio.Event()
        task = None
        if settings.imported_storage_cleanup_enabled and settings.environment != 'test':
            from app.workers.imported_storage_cleanup import run_cleanup
            task = asyncio.create_task(run_cleanup(application, stop))
        try:
            yield
        finally:
            stop.set()
            if task:
                await task
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
                               allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
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
        message = "Duplicate record or conflicting relationship"
        return JSONResponse(status_code=409, content={"detail": message, "error": message, "message": message})

    @application.exception_handler(StaleDataError)
    async def stale_error(request, exc):
        return JSONResponse(status_code=409, content={"detail": "Record changed concurrently; reload and retry"})

    @application.exception_handler(OperationalError)
    async def database_error(request, exc):
        logging.getLogger(__name__).error("Database operation failed, request=%s", request.state.correlation_id)
        return JSONResponse(status_code=503, content={"detail": "Database unavailable or busy; retry later"})

    application.include_router(api_router, prefix="/api/v1")
    from app.modules.recruiting.pipeline_api import router as pipeline_router
    application.include_router(pipeline_router)
    from app.modules.recruiting.pipeline_interviews import router as interview_pipeline_router
    application.include_router(interview_pipeline_router)
    from app.modules.recruiting.pipeline_feedback import router as feedback_pipeline_router
    application.include_router(feedback_pipeline_router)
    from app.modules.recruiting.pipeline_jobs import router as jobs_compat_router
    from app.modules.recruiting.pipeline_analytics import router as analytics_compat_router
    from app.modules.recruiting.pipeline_configuration import router as configuration_compat_router
    application.include_router(jobs_compat_router)
    application.include_router(analytics_compat_router)
    application.include_router(configuration_compat_router)
    from app.modules.workforce.imported_assets import router as asset_compat_router
    from app.modules.workforce.imported_asset_returns import router as asset_return_router
    application.include_router(asset_return_router)
    application.include_router(asset_compat_router)
    from app.modules.workforce.imported_shared import router as shared_compat_router
    application.include_router(shared_compat_router)
    from app.modules.workforce.imported_organization import router as org_compat_router
    application.include_router(org_compat_router)
    from app.modules.workforce.imported_employees import router as employee_compat_router
    application.include_router(employee_compat_router)
    from app.modules.workforce.imported_employee_profile import router as employee_profile_router
    application.include_router(employee_profile_router)
    from app.modules.workforce.imported_documents import router as document_compat_router
    application.include_router(document_compat_router)
    from app.modules.workforce.imported_asset_incidents import router as asset_incident_router
    application.include_router(asset_incident_router)
    from app.modules.workforce.imported_employee_assets import router as employee_asset_router
    application.include_router(employee_asset_router)
    from app.modules.workforce.imported_leave import router as leave_compat_router
    from app.modules.workforce.imported_attendance import router as attendance_compat_router
    application.include_router(leave_compat_router)
    application.include_router(attendance_compat_router)
    from app.modules.workforce.imported_attendance_views import router as attendance_view_router
    application.include_router(attendance_view_router)
    from app.modules.workforce.imported_leave_calendar import router as leave_calendar_router
    from app.modules.workforce.imported_attendance_reports import router as attendance_report_router
    application.include_router(leave_calendar_router)
    application.include_router(attendance_report_router)
    from app.modules.workforce.imported_self_service import router as self_service_router
    application.include_router(self_service_router)
    from app.modules.workforce.imported_photo import router as photo_router
    application.include_router(photo_router)
    from app.modules.workforce.imported_onboarding import router as imported_onboarding_router
    application.include_router(imported_onboarding_router)
    from app.modules.workforce.imported_probation import router as imported_probation_router
    application.include_router(imported_probation_router)
    from app.modules.workforce.imported_tasks import router as imported_tasks_router
    from app.modules.workforce.imported_privacy import router as imported_privacy_router
    application.include_router(imported_tasks_router)
    application.include_router(imported_privacy_router)
    from app.modules.workforce.imported_exits import router as imported_exits_router
    from app.modules.workforce.imported_exit_clearance import router as imported_exit_clearance_router
    application.include_router(imported_exits_router)
    application.include_router(imported_exit_clearance_router)
    from app.modules.workforce.imported_settlements import router as imported_settlements_router
    application.include_router(imported_settlements_router)
    from app.modules.workforce.imported_recruitment import router as employee_recruitment_router
    application.include_router(employee_recruitment_router)
    from app.modules.workforce.imported_performance import router as imported_performance_router
    application.include_router(imported_performance_router)
    from app.modules.workforce.imported_dashboards import router as imported_dashboards_router
    application.include_router(imported_dashboards_router)
    from app.modules.workforce.imported_support import router as imported_support_router
    application.include_router(imported_support_router)
    from app.modules.workforce.imported_knowledge import router as imported_knowledge_router
    application.include_router(imported_knowledge_router)
    from app.modules.workforce.imported_helpdesk_settings import router as imported_helpdesk_settings_router
    application.include_router(imported_helpdesk_settings_router)
    from app.modules.workforce.imported_helpdesk_reports import router as imported_helpdesk_reports_router
    application.include_router(imported_helpdesk_reports_router)
    from app.modules.workforce.imported_hierarchy import router as imported_hierarchy_router
    application.include_router(imported_hierarchy_router)
    from app.modules.workforce.imported_accounts import router as imported_accounts_router
    application.include_router(imported_accounts_router)
    from app.modules.workforce.imported_company import router as imported_company_router
    application.include_router(imported_company_router)
    from app.modules.workforce.imported_misc import router as imported_misc_router
    application.include_router(imported_misc_router)
    from app.modules.workforce.imported_parties import router as imported_parties_router
    application.include_router(imported_parties_router)
    from app.modules.workforce.imported_roles import router as imported_roles_router
    from app.modules.workforce.imported_views import router as imported_views_router
    application.include_router(imported_roles_router)
    application.include_router(imported_views_router)
    from app.modules.interviews.imported_email import router as imported_email_router
    application.include_router(imported_email_router)
    from app.modules.workforce.imported_subscriptions import router as imported_subscriptions_router
    application.include_router(imported_subscriptions_router)
    from app.modules.workforce.imported_setup import router as imported_setup_router
    application.include_router(imported_setup_router)
    return application


app = create_app()
