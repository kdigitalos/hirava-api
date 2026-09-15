"""Own profile photo updates with transactionally queued old-object cleanup."""
import logging
from pathlib import PurePosixPath
from uuid import uuid4

from fastapi import Depends, HTTPException, Request, Response
from starlette.datastructures import UploadFile

from app.core import imported_storage
from app.core.compatibility_routing import APIRouter, CompatibilityRoute
from app.core.imported_identity import linked_employee
from app.data.database import get_db
from app.data.imported import find
from app.modules.workforce.imported_employee_profile import details
from app.modules.workforce.imported_leave import staff
from app.modules.workforce.imported_organization import update
from app.workers.imported_storage_cleanup import queue_delete


class PhotoRoute(CompatibilityRoute):
    max_body_bytes = 5 * 1024 * 1024 + 65536


router = APIRouter(prefix='/api/my-profile/photo', tags=['HRMS profile photo'], route_class=PhotoRoute)
MIMES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}


def replace_photo(db, user, employee, key):
    metadata = dict(details(employee))
    previous = metadata.get('employeePhoto')
    metadata['employeePhoto'] = key
    update(db, 'Employee', employee['id'], {'employeeDetails': metadata})
    if isinstance(previous, str) and previous != key and previous.startswith(f"employees/{employee['id']}/"):
        queue_delete(db, user.customer_id, previous)


@router.post('')
async def upload_photo(request: Request, user=Depends(staff), db=Depends(get_db)):
    employee = find(db, 'Employee', linked_employee(db, user)['id'], lock=True)
    async with request.form() as form:
        file = form.get('file')
        if not isinstance(file, UploadFile):
            raise HTTPException(422, 'Choose a profile photo')
        suffix = PurePosixPath(file.filename or '').suffix.lower()
        if suffix not in MIMES or file.content_type != MIMES[suffix]:
            raise HTTPException(422, 'Use a JPG, PNG or WebP photo')
        content = await file.read(5 * 1024 * 1024 + 1)
        if not content or len(content) > 5 * 1024 * 1024:
            raise HTTPException(422, 'Profile photos must be between 1 byte and 5 MB')
    key = f"employees/{employee['id']}/{uuid4().hex}{suffix}"
    settings = request.app.state.settings
    imported_storage.save(settings, key, content, MIMES[suffix])
    try:
        replace_photo(db, user, employee, key)
        db.commit()
    except Exception:
        db.rollback()
        try:
            imported_storage.remove(settings, key)
        except Exception:
            logging.getLogger(__name__).warning('New profile photo cleanup failed')
        raise
    return {'employeePhoto': key, 'photoUrl': '/api/uploads/' + key}


@router.delete('')
def delete_photo(user=Depends(staff), db=Depends(get_db)):
    employee = find(db, 'Employee', linked_employee(db, user)['id'], lock=True)
    replace_photo(db, user, employee, None)
    return Response(status_code=204)
