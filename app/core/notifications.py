"""Transactional in-app notifications. Never sends email or external messages."""
from sqlalchemy import select

from app.core.models import Notification, OutboxEvent, User
from app.data.imported import table


def deliver(db, actor, recipient_id, message, href):
    recipient = db.scalar(select(User).where(
        User.id == recipient_id, User.customer_id == actor.customer_id, User.active.is_(True)))
    if not recipient:
        return
    event = OutboxEvent(customer_id=actor.customer_id, topic="notification", status="delivered",
                        payload={"user_id": recipient.id, "message": message[:250], "href": href})
    db.add(event)
    db.flush()
    db.add(Notification(customer_id=actor.customer_id, event_id=event.id,
                        user_id=recipient.id, message=message[:250]))


def employee_notification(db, actor, employee_id, message, href):
    employee, bridge = table(db, 'Employee'), table(db, 'User')
    subject = db.scalar(select(bridge.c.auth0Sub).join(employee, employee.c.userId == bridge.c.id)
                        .where(employee.c.id == employee_id))
    if not subject:
        return
    accounts = db.scalars(select(User).where(User.customer_id == actor.customer_id, User.active.is_(True)))
    recipient = next((account for account in accounts
                      if (account.auth_subject or f'local|{account.id}') == subject), None)
    if recipient:
        deliver(db, actor, recipient.id, message, href)


def notify_reviewers(db, actor, message, href):
    """Notify active HR/admin reviewers in this customer, never the submitting actor."""
    recipient_ids = db.scalars(select(User.id).where(
        User.customer_id == actor.customer_id, User.active.is_(True),
        User.role.in_(('admin', 'hr')), User.id != actor.id)).all()
    for recipient_id in recipient_ids:
        deliver(db, actor, recipient_id, message, href)
