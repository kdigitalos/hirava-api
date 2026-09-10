"""Durable local notification delivery; no external provider writes."""
import argparse
import time
from sqlalchemy import select
from app.core.config import Settings
from app.core.models import Notification, OutboxEvent, User
from app.data import registry  # noqa: F401
from app.data.database import build_engine, session_factory


def process_batch(sessions, customer_id, limit=50):
    delivered = 0
    # One transaction per event: receipt and event status commit together.
    for _ in range(limit):
        with sessions.begin() as db:
            event = db.scalar(select(OutboxEvent).where(OutboxEvent.customer_id == customer_id,
                OutboxEvent.status == "pending").order_by(OutboxEvent.created_at).with_for_update(skip_locked=True).limit(1))
            if event is None:
                break
            event.attempts += 1
            payload = event.payload if isinstance(event.payload, dict) else {}
            recipient = db.scalar(select(User).where(User.id == payload.get("user_id"), User.customer_id == customer_id))
            message = payload.get("message")
            if event.topic != "notification" or not recipient or not isinstance(message, str) or not 1 <= len(message) <= 250:
                event.last_error = "Unsupported event or unknown recipient"
                if event.attempts >= 3:
                    event.status = "failed"
                continue
            existing = db.scalar(select(Notification).where(Notification.event_id == event.id))
            if not existing:
                db.add(Notification(customer_id=customer_id, event_id=event.id, user_id=recipient.id,
                                     message=message))
            event.status, event.last_error = "delivered", None
            delivered += 1
    return delivered


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    engine = build_engine(settings.database_url)
    sessions = session_factory(engine)
    try:
        while True:
            delivered = process_batch(sessions, settings.customer_id)
            if args.once:
                print(f"Delivered {delivered} local notifications")
                break
            time.sleep(5)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
