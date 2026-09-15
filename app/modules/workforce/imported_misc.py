"""Health and administrative search compatibility, without the private server."""
from fastapi import Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import or_, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.compatibility_routing import APIRouter
from app.data.database import get_db, utcnow
from app.data.imported import dto, table
from app.modules.workforce.imported_leave import admin

router = APIRouter(prefix='/api', tags=['Administrative compatibility'])


@router.get('/health')
def health(db=Depends(get_db)):
    try:
        db.execute(text('SELECT 1'))
    except SQLAlchemyError:
        db.rollback()
        return JSONResponse({'status': 'unavailable', 'database': 'down', 'timestamp': utcnow().isoformat()}, status_code=503)
    return {'status': 'ok', 'database': 'up', 'timestamp': utcnow().isoformat()}


@router.get('/admin/payroll-activities')
def payroll_activities(user=Depends(admin)):
    # The previous route had no payroll activity source. Do not invent payments.
    return {'rows': [], 'available': False, 'message': 'Payroll activity tracking is not configured.'}


@router.get('/search')
def search(q: str = Query('', max_length=200), user=Depends(admin), db=Depends(get_db)):
    query = q.strip()
    if not query:
        return {'results': []}
    employee, ticket = table(db, 'Employee'), table(db, 'SupportTicket')
    pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    def matched(tbl, fields):
        statement = select(tbl).where(or_(*(tbl.c[field].ilike(pattern, escape='\\') for field in fields))).order_by(tbl.c.id).limit(10)
        return [dto(tbl, row) for row in db.execute(statement).mappings()]
    people = matched(employee, ('firstName', 'lastName', 'email', 'employeeCode'))
    tickets = matched(ticket, ('ticketNumber', 'title', 'description'))
    return {'results': [
        *({'type': 'employee', 'id': row['id'], 'title': ' '.join(part for part in (row['firstName'], row['lastName']) if part),
           'subtitle': row['email'], 'href': '/HRMS/Admin/EmployeeManagement/profile-management/' + row['id']} for row in people),
        *({'type': 'ticket', 'id': row['id'], 'title': row['ticketNumber'], 'subtitle': row['title'],
           'href': '/HRMS/Admin/AskMe/tickets'} for row in tickets)]}
