import hashlib
import time
from datetime import timedelta, timezone
from pathlib import Path
from uuid import uuid4

from app.core.routing import APIRouter
from fastapi import Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Acknowledgement, AuditEvent, Document, Notification, OutboxEvent, Policy, User
from app.core.schemas import Login, PolicyCreate, UserCreate, UserUpdate
from app.core.security import current_user, hash_password, issue_token, require, verify_password
from app.core.service import audit, find, rows, view
from app.data.database import get_db, utcnow

router = APIRouter(tags=["core"])


@router.post("/auth/login")
def login(body: Login, request: Request, db: Session = Depends(get_db)):
    settings = request.app.state.settings
    if settings.auth_mode != "local":
        raise HTTPException(404, "Use your Auth0 login flow")
    # Local development protection; deployed login is delegated to Auth0.
    host = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with request.app.state.login_lock:
        attempts = request.app.state.login_attempts
        recent = [instant for instant in attempts.get(host, []) if instant > now - 60]
        if len(recent) >= 10:
            raise HTTPException(429, "Too many attempts; retry in one minute")
        attempts[host] = recent + [now]
    user = db.scalar(select(User).where(User.customer_id == settings.customer_id, User.email == str(body.email).lower()).with_for_update())
    if user and user.locked_until and user.locked_until.replace(tzinfo=timezone.utc) > utcnow():
        raise HTTPException(401, "Invalid credentials")
    valid = verify_password(body.password, user.password_hash if user else None)
    if not user or not user.active or not valid:
        if user:
            user.failed_logins += 1
            if user.failed_logins >= 5:
                user.locked_until = utcnow() + timedelta(minutes=5)
            db.commit()  # Failure counters must survive the HTTP exception.
        raise HTTPException(401, "Invalid credentials")
    user.failed_logins = 0
    user.locked_until = None
    audit(db, user, "auth.login", user, request)
    return {"access_token": issue_token(user, settings), "token_type": "bearer", "expires_in": settings.token_minutes * 60}


@router.get("/auth/me")
def me(user=Depends(current_user)):
    return view(user)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    if request.app.state.settings.auth_mode != "local":
        raise HTTPException(409, "Use Auth0 logout; deactivate a user to revoke application access")
    user.token_version += 1
    audit(db, user, "auth.logout_all_local_sessions", user, request)


@router.post("/users", status_code=201)
def create_user(body: UserCreate, request: Request, user=Depends(require("admin")), db: Session = Depends(get_db)):
    local = request.app.state.settings.auth_mode == "local"
    if local and body.password is None:
        raise HTTPException(422, "A local user requires a password")
    if not local and (not body.auth_subject or body.password):
        raise HTTPException(422, "Auth0 users require auth_subject and no local password")
    record = User(customer_id=user.customer_id, email=str(body.email).lower(), name=body.name,
                  role=body.role, password_hash=hash_password(body.password) if local else None,
                  auth_subject=body.auth_subject)
    db.add(record)
    audit(db, user, "user.created", record, request)
    return view(record)


@router.get("/users")
def list_users(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
               user=Depends(require("admin")), db: Session = Depends(get_db)):
    return [view(row) for row in rows(db, User, user.customer_id, offset, limit)]


@router.patch("/users/{record_id}")
def update_user(record_id: str, body: UserUpdate, request: Request,
                user=Depends(require("admin")), db: Session = Depends(get_db)):
    record = find(db, User, record_id, user.customer_id, lock=True)
    if record.id == user.id:
        raise HTTPException(409, "Cannot deactivate your own administrator account")
    record.active = body.active
    record.token_version += 1
    audit(db, user, "user.access_changed", record, request)
    return view(record)


@router.get("/configuration")
def configuration(request: Request, user=Depends(current_user)):
    settings = request.app.state.settings
    return {"customer_id": user.customer_id, "modules": {"rms": settings.rms_enabled, "hrms": settings.hrms_enabled},
            "auth_mode": settings.auth_mode, "ai_enabled": False, "external_writes_enabled": False}


@router.get("/audit")
def list_audit(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
               user=Depends(require("admin")), db: Session = Depends(get_db)):
    return [view(row) for row in rows(db, AuditEvent, user.customer_id, offset, limit)]


@router.get("/outbox")
def outbox(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
           user=Depends(require("admin")), db: Session = Depends(get_db)):
    return [view(row) for row in rows(db, OutboxEvent, user.customer_id, offset, limit)]


@router.post("/outbox/{record_id}/retry")
def retry_event(record_id: str, request: Request, user=Depends(require("admin")), db: Session = Depends(get_db)):
    record = find(db, OutboxEvent, record_id, user.customer_id, lock=True)
    if record.status != "failed":
        raise HTTPException(409, "Only failed events can be retried")
    record.status, record.attempts, record.last_error = "pending", 0, None
    audit(db, user, "outbox.retry_requested", record, request)
    return view(record)


@router.get("/notifications")
def notifications(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                  user=Depends(current_user), db: Session = Depends(get_db)):
    return [view(row) for row in rows(db, Notification, user.customer_id, offset, limit, Notification.user_id == user.id)]


@router.post("/notifications/{record_id}/read")
def read_notification(record_id: str, user=Depends(current_user), db: Session = Depends(get_db)):
    record = find(db, Notification, record_id, user.customer_id)
    if record.user_id != user.id:
        raise HTTPException(404, "Record not found")
    record.read = True
    return view(record)


@router.post("/policies", status_code=201)
def create_policy(body: PolicyCreate, request: Request, user=Depends(require("hr")), db: Session = Depends(get_db)):
    record = Policy(customer_id=user.customer_id, **body.model_dump())
    db.add(record)
    audit(db, user, "policy.published", record, request)
    return view(record)


@router.get("/policies")
def policies(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
             user=Depends(require("hr", "manager", "employee", "recruiter", "interviewer")), db: Session = Depends(get_db)):
    return [view(row) for row in rows(db, Policy, user.customer_id, offset, limit)]


@router.post("/policies/{record_id}/acknowledge")
def acknowledge(record_id: str, request: Request,
                user=Depends(require("hr", "manager", "employee", "recruiter", "interviewer")), db: Session = Depends(get_db)):
    record = find(db, Policy, record_id, user.customer_id)
    existing = db.scalar(select(Acknowledgement).where(Acknowledgement.policy_id == record.id,
                         Acknowledgement.user_id == user.id, Acknowledgement.revision == record.revision))
    if existing:
        return view(existing)
    acknowledgement = Acknowledgement(customer_id=user.customer_id, policy_id=record.id, user_id=user.id, revision=record.revision)
    db.add(acknowledgement)
    audit(db, user, "policy.acknowledged", acknowledgement, request)
    return view(acknowledgement)


def document_access(record, user, settings):
    if not getattr(settings, f"{record.domain}_enabled"):
        raise HTTPException(403, "Module disabled")
    allowed = {"rms": {"admin", "recruiter"}, "hrms": {"admin", "hr"}}
    if user.role not in allowed[record.domain]:
        raise HTTPException(404, "Document not found")


@router.post("/documents", status_code=201)
def upload_document(request: Request, domain: str = Query(pattern="^(rms|hrms)$"), file: UploadFile = File(...),
                    user=Depends(current_user), db: Session = Depends(get_db)):
    settings = request.app.state.settings
    record = Document(customer_id=user.customer_id, owner_id=user.id, domain=domain,
                      filename=Path(file.filename or "document").name[:255], storage_key=str(uuid4()), size=0, sha256="")
    document_access(record, user, settings)
    destination = settings.storage_path / settings.customer_id / record.storage_key
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    try:
        with destination.open("xb") as target:
            while chunk := file.file.read(65536):
                record.size += len(chunk)
                if record.size > settings.max_upload_bytes:
                    raise HTTPException(413, "Document is too large")
                digest.update(chunk)
                target.write(chunk)
        record.sha256 = digest.hexdigest()
        db.add(record)
        audit(db, user, "document.uploaded", record, request)
        db.commit()
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        file.file.close()
    return view(record)


@router.get("/documents/{record_id}")
def download_document(record_id: str, request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    record = find(db, Document, record_id, user.customer_id)
    settings = request.app.state.settings
    document_access(record, user, settings)
    path = settings.storage_path / settings.customer_id / record.storage_key
    if not path.is_file():
        raise HTTPException(404, "Document content unavailable")
    audit(db, user, "document.downloaded", record, request)
    return FileResponse(path, filename=record.filename, media_type="application/octet-stream",
                        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})
