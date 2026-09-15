"""Shared identity and private upload compatibility, without the Node service."""
import mimetypes
from pathlib import PurePosixPath
from uuid import uuid4

from fastapi import Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from starlette.datastructures import UploadFile

from app.core.compatibility_routing import APIRouter, CompatibilityRoute
from app.core import imported_storage
from app.core.imported_identity import linked_employee
from app.core.security import current_user
from app.data.database import get_db
from app.data.imported import dto, table
from app.modules.workforce.imported_assets import insert, now, wire


class UploadRoute(CompatibilityRoute):
    max_body_bytes = 5 * 1024 * 1024 + 65536


router = APIRouter(prefix='/api', tags=['Shared imported APIs'], route_class=UploadRoute)


def bridge_user(db, user):
    bridge = table(db, 'User')
    subject = user.auth_subject or f'local|{user.id}'
    record = db.execute(select(bridge).where(bridge.c.auth0Sub == subject).with_for_update()).mappings().first()
    values = {'name': user.name, 'email': user.email,
              'role': {'admin': 'ADMIN', 'hr': 'HR', 'manager': 'MANAGER'}.get(user.role, 'EMPLOYEE')}
    if record:
        return dto(bridge, db.execute(bridge.update().where(bridge.c.id == record[bridge.c.id])
                   .values(**values, updatedAt=now()).returning(bridge)).mappings().one())
    # Never adopt another identity through an email match.
    if db.execute(select(bridge.c.id).where(bridge.c.email == user.email)).first():
        raise HTTPException(409, 'An imported account already uses this email; reconcile its identity')
    return insert(db, 'User', {**values, 'auth0Sub': subject})


@router.get('/users/me')
def me(user=Depends(current_user), db=Depends(get_db)):
    return wire(bridge_user(db, user))


@router.get('/session/employee')
def employee_session(user=Depends(current_user), db=Depends(get_db)):
    bridge = bridge_user(db, user)
    employee = linked_employee(db, user, required=False)
    if not employee:
        raise HTTPException(401, 'Unauthorized or no employee profile linked to this account')
    return {'user': {key: bridge[key] for key in ('id', 'email', 'role', 'name')},
            'employee': {key: employee[key] for key in ('id', 'employeeCode', 'firstName', 'lastName', 'email')}}


ALLOWED_FILES = {'.pdf': 'application/pdf', '.doc': 'application/msword',
                 '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                 '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.txt': 'text/plain'}


@router.post('/upload')
async def upload(request: Request, user=Depends(current_user)):
    if 'multipart/form-data' not in request.headers.get('content-type', ''):
        raise HTTPException(415, 'Use multipart/form-data with a file')
    async with request.form(max_files=1, max_fields=10) as form:
        file = form.get('file')
        if not isinstance(file, UploadFile) or not file.filename:
            raise HTTPException(422, 'Choose a file to upload')
        extension = PurePosixPath(file.filename).suffix.lower()
        if extension not in ALLOWED_FILES:
            raise HTTPException(422, 'Use PDF, Word, JPG, PNG or TXT')
        content = await file.read(5 * 1024 * 1024 + 1)
        if not content or len(content) > 5 * 1024 * 1024:
            raise HTTPException(413, 'Choose a nonempty file no larger than 5 MB')
        filename = file.filename
    key = f'user-uploads/{user.id}/{uuid4().hex}{extension}'
    imported_storage.save(request.app.state.settings, key, content, ALLOWED_FILES[extension])
    url = '/api/uploads/' + key
    return {'success': True, 'fileUrl': url, 'fileName': filename, 'filePath': url}


@router.get('/uploads/{path:path}')
def download(path: str, request: Request, user=Depends(current_user), db=Depends(get_db)):
    imported_storage.safe_key(path)
    from app.workers.imported_storage_cleanup import is_deleted
    if is_deleted(db, user.customer_id, path):
        raise HTTPException(404, 'File is unavailable')
    segments = path.split('/')
    if len(segments) < 3:
        raise HTTPException(400, 'Invalid file path')
    category, owner = segments[:2]
    if user.role not in ('admin', 'hr'):
        if category == 'employee-documents':
            employee = linked_employee(db, user)
            if owner != employee['id']:
                raise HTTPException(403, 'File access denied')
        elif category == 'exit-requests':
            from app.modules.workforce.imported_exits import exit_record
            exit_record(db, owner, user)
        elif category == 'user-uploads':
            if owner != user.id and user.role != 'recruiter':
                raise HTTPException(403, 'File access denied')
        elif category not in ('employees', 'organization'):
            raise HTTPException(403, 'File access denied')
    stream, mime = imported_storage.open_file(request.app.state.settings, path)
    def chunks():
        try:
            while chunk := stream.read(65536):
                yield chunk
        finally:
            stream.close()
    return StreamingResponse(chunks(), media_type=mime or mimetypes.guess_type(path)[0],
                             headers={'Cache-Control': 'private, no-store'})
