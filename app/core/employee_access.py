"""Explicit identity link to the retained, single-customer employee directory.

No employee is inferred from an email address. The native user remains the
identity authority; this transaction only maintains the compatibility link.
"""
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text


def employee_link(db, account):
    subject = account.auth_subject or f"local|{account.id}"
    return db.execute(text('SELECT e.id, e.employee_code, e.first_name, e.last_name '
        'FROM public."Employee" e JOIN public."User" u ON e.user_id=u.id '
        'WHERE u.auth0_sub=:subject'), {"subject": subject}).mappings().first()


def set_employee_link(db, account, employee_id):
    subject = account.auth_subject or f"local|{account.id}"
    lock = " FOR UPDATE" if db.bind.dialect.name == "postgresql" else ""
    bridge = db.execute(text('SELECT id, email FROM public."User" WHERE auth0_sub=:subject' + lock),
                        {"subject": subject}).mappings().first()
    linked = employee_link(db, account)
    if employee_id is None:
        if linked:
            db.execute(text('UPDATE public."Employee" SET user_id=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=:id'), {"id": linked['id']})
        return None
    if not account.active:
        raise HTTPException(409, "Activate the account before linking an employee")
    employee = db.execute(text('SELECT id, employee_code, first_name, last_name, user_id, status '
        'FROM public."Employee" WHERE id=:id' + lock), {"id": employee_id}).mappings().first()
    if not employee:
        raise HTTPException(404, "Employee not found")
    if employee['status'] == 'TERMINATED':
        raise HTTPException(409, "A terminated employee cannot receive new login access")
    if linked and linked['id'] != employee_id:
        raise HTTPException(409, "Unlink the current employee before linking another")
    if employee['user_id'] and (not bridge or employee['user_id'] != bridge['id']):
        raise HTTPException(409, "This employee already has a linked account")
    if not bridge:
        duplicate = db.execute(text('SELECT id FROM public."User" WHERE email=:email'), {"email": account.email}).first()
        if duplicate:
            raise HTTPException(409, "An imported account already uses this email; reconcile its identity before linking")
        bridge = {"id": str(uuid4())}
        db.execute(text('INSERT INTO public."User" (id, auth0_sub, email, name, role, created_at, updated_at) '
            'VALUES (:id,:subject,:email,:name,:role,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)'),
            {"id": bridge['id'], "subject": subject, "email": account.email, "name": account.name,
             "role": {"admin": "ADMIN", "hr": "HR", "manager": "MANAGER"}.get(account.role, "EMPLOYEE")})
    db.execute(text('UPDATE public."Employee" SET user_id=:user_id, updated_at=CURRENT_TIMESTAMP WHERE id=:id'),
               {"id": employee_id, "user_id": bridge['id']})
    return employee_link(db, account)
