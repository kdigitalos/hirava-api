"""Resolve imported employee ownership from the verified native account."""
from fastapi import HTTPException
from sqlalchemy import select

from app.data.imported import dto, table


def linked_employee(db, account, required=True):
    employee, bridge = table(db, 'Employee'), table(db, 'User')
    subject = account.auth_subject or f'local|{account.id}'
    row = db.execute(select(employee).join(bridge, employee.c.userId == bridge.c.id)
                     .where(bridge.c.auth0Sub == subject)).mappings().first()
    if row is None:
        if required:
            raise HTTPException(403, 'No employee record linked to your account')
        return None
    return dto(employee, row)
