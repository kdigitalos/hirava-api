"""Durable file deletion retries inside the FastAPI process; no extra terminal."""
import asyncio
import logging

from sqlalchemy import select

from app.core import imported_storage
from app.core.models import OutboxEvent

TOPIC = 'imported.storage.delete'


def queue_delete(db, customer_id, key):
    imported_storage.safe_key(key)
    db.add(OutboxEvent(customer_id=customer_id, topic=TOPIC, payload={'key': key}))


def is_deleted(db, customer_id, key):
    return db.scalar(select(OutboxEvent.id).where(OutboxEvent.customer_id == customer_id, OutboxEvent.topic == TOPIC,
        OutboxEvent.payload['key'].as_string() == key).limit(1)) is not None


def process_deletions(sessions, settings, limit=5):
    completed = 0
    # One bounded snapshot per pass: a failed key is retried on the next pass.
    with sessions() as db:
        ids = db.scalars(select(OutboxEvent.id).where(OutboxEvent.customer_id == settings.customer_id,
            OutboxEvent.topic == TOPIC, OutboxEvent.status == 'pending').order_by(OutboxEvent.attempts, OutboxEvent.created_at).limit(limit)).all()
    for event_id in ids:
        with sessions.begin() as db:
            event = db.scalar(select(OutboxEvent).where(OutboxEvent.id == event_id, OutboxEvent.status == 'pending')
                .with_for_update(skip_locked=True))
            if event is None:
                continue
            event.attempts += 1
            try:
                imported_storage.remove(settings, event.payload['key'])
            except Exception:
                # Keep retrying. Do not record credentials, bucket names or signed URLs.
                event.last_error = 'Object removal failed; retry pending'
            else:
                event.status, event.last_error = 'delivered', None
                completed += 1
    return completed


async def run_cleanup(application, stop):
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=30)
            return
        except TimeoutError:
            pass
        try:
            await asyncio.to_thread(process_deletions, application.state.sessions, application.state.settings)
        except Exception:
            logging.getLogger(__name__).warning('Storage cleanup unavailable; retrying on the next pass')
