"""Bounded worker invocations; no startup loops or unauthenticated job triggers."""
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request

router = APIRouter(prefix="/api/internal/cron", include_in_schema=False)


def authorize(request: Request):
    settings = request.app.state.settings
    secret = settings.cron_secret.get_secret_value()
    supplied = request.headers.get("authorization", "")
    if not settings.vercel or not secret or not secrets.compare_digest(
        supplied.encode(), ("Bearer " + secret).encode()
    ):
        raise HTTPException(401, "Unauthorized")


@router.get("/maintenance", dependencies=[Depends(authorize)])
def maintenance(request: Request):
    from app.workers.outbox import process_batch
    from app.workers.imported_storage_cleanup import process_deletions
    from app.agents.operations_worker import scan_once

    app = request.app
    settings = app.state.settings
    notifications = process_batch(app.state.sessions, settings.customer_id, limit=50)
    deleted = 0
    if settings.imported_storage_cleanup_enabled:
        deleted = process_deletions(app.state.sessions, settings, limit=5)
    if settings.recruitment_operations_enabled:
        scan_once(app)
    return {"notifications": notifications, "files_deleted": deleted}


@router.get("/screening", dependencies=[Depends(authorize)])
def screening(request: Request):
    from app.agents.application import process_one

    # Existing database CAS claim prevents two invocations processing one job.
    # Interrupted paid requests are not automatically resubmitted.
    return {"processed": process_one(request.app)}
