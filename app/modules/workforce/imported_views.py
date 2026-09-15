"""Read-only page loaders used by retained server-rendered pages."""
from datetime import timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from app.core.compatibility_routing import APIRouter
from app.core.imported_identity import linked_employee
from app.core.models import User
from app.data.database import get_db
from app.data.imported import table
from app.modules.workforce.imported_assets import now, rows
from app.modules.workforce.imported_leave import staff, output
from app.modules.workforce.imported_profile_view import employee_profile
from app.modules.workforce.imported_self_service import profile_payload

router = APIRouter(prefix='/api/views', tags=['Page data compatibility'])


def own_tasks(db, user):
    employee = linked_employee(db, user, required=False)
    if not employee:
        return []
    tasks = table(db, 'EmployeeTask')
    result = []
    for row in rows(db, 'EmployeeTask', tasks.c.employeeId == employee['id'], order=tasks.c.dueDate):
        due = row['dueDate']
        kind = (row['detailKind'] or '').strip().lower().replace('_', '-')
        steps = row['nextStepsJson'] if isinstance(row['nextStepsJson'], list) else []
        result.append({'id': row['id'], 'name': row['title'], 'description': row['description'], 'source': row['source'].title(),
            'dueDate': due.strftime('%d-%m-%Y'), 'dueIso': due.isoformat()[:10],
            'status': 'Completed' if row['status'] == 'COMPLETED' else 'Overdue' if due.isoformat()[:10] < now().date().isoformat() else 'In Progress',
            'detailKind': 'emergency-contact' if kind == 'emergency-contact' else 'generic',
            'nextSteps': [value.strip() for value in steps if isinstance(value, str) and value.strip()][:20]})
    return result


def onboarding_groups(db, params):
    groups = rows(db, 'OnboardingGroup', order=table(db, 'OnboardingGroup').c.updatedAt.desc())
    candidates = rows(db, 'OnboardingCandidate')
    by_group = {}
    for candidate in candidates:
        by_group.setdefault(candidate['groupId'], []).append(candidate)
    today = now().date()
    end = today + timedelta(days=1)
    status, role, query = params.get('status', '').upper(), params.get('role', ''), params.get('q', '').strip().casefold()
    def matches(group):
        if group['name'] == '__hirava_candidates_page__' or role and group['roleLabel'] != role or query not in group['name'].casefold():
            return False
        linked = by_group.get(group['id'], [])
        start, stop = group['windowStart'], group['windowEnd']
        active = group['status'] == 'ACTIVE'
        if status in ('ACTIVE', 'DRAFT', 'CONVERSION_PENDING', 'ARCHIVED'):
            return group['status'] == status
        if status == 'NOT_STARTED':
            return active and bool(start and start > today)
        if status == 'IN_PROGRESS':
            return active and (not start or start < end) and (not stop or stop >= today)
        if status == 'PENDING_APPROVAL':
            return any(row['status'] == 'INVITED' for row in linked)
        if status == 'REJECTED':
            return any(row['status'] == 'WITHDRAWN' for row in linked)
        if status == 'COMPLETED':
            return group['status'] == 'ARCHIVED' or active and bool(stop and stop < today) or bool(linked and all(row['status'] == 'COMPLETED' for row in linked))
        return True
    selected = [group for group in groups if matches(group)]
    counts = {group['id']: len(by_group.get(group['id'], [])) for group in selected}
    return output({'groups': selected, 'candidateCounts': counts, 'activeCount': sum(group['status'] == 'ACTIVE' for group in selected),
        'startingSoonCount': sum(bool(group['status'] == 'ACTIVE' and group['windowStart'] and group['windowStart'] > today) for group in selected),
        'draftCount': sum(group['status'] == 'DRAFT' for group in selected), 'totalCandidates': sum(counts.values()),
        'roleOptions': sorted({group['roleLabel'].strip() for group in groups if group['roleLabel'] and group['roleLabel'].strip()}), 'loadError': None})


@router.get('/{name}')
def view(name: str, request: Request, user=Depends(staff), db=Depends(get_db)):
    if name in ('onboarding-groups', 'policy-stats', 'organization-roles') and user.role not in ('admin', 'hr'):
        raise HTTPException(403, 'HR or administrator access required')
    if name == 'onboarding-groups':
        return onboarding_groups(db, request.query_params)
    if name == 'policy-stats':
        roles = list(db.scalars(select(User.role).where(User.customer_id == user.customer_id)))
        return {'totalRoles': len(set(roles)), 'customRoles': len(set(roles) & {'hr', 'manager'}), 'totalUsers': len(roles), 'modules': 10}
    if name == 'my-tasks':
        return own_tasks(db, user)
    if name == 'my-task':
        return next((task for task in own_tasks(db, user) if task['id'] == request.query_params.get('id')), None)
    if name == 'ess-profile':
        employee = linked_employee(db, user, required=False)
        return output({'employee': {'id': employee['id'], 'employeeDetails': employee['employeeDetails']} if employee else None,
                       'payload': profile_payload(db, employee) if employee else None})
    if name == 'employee-profile':
        return employee_profile(db, user)
    if name == 'employee-dashboard':
        from app.modules.workforce.imported_employee_dashboard import employee_dashboard
        return employee_dashboard(db, user)
    if name == 'organization-roles':
        if user.role != 'admin':
            raise HTTPException(403, 'Administrator access required')
        from app.modules.workforce.imported_roles import listing
        return listing(db, user)
    raise HTTPException(404, 'Unknown page data')
