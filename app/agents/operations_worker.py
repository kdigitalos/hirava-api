"""Periodic local work detection. Never calls an AI or external message provider."""
import asyncio
import logging
from types import SimpleNamespace
from app.agents.operations import scan_signals


def scan_once(app):
    with app.state.sessions.begin() as db:
        scan_signals(db, SimpleNamespace(customer_id=app.state.settings.customer_id))


async def run_operations(app, stop):
    while not stop.is_set():
        try:
            await asyncio.to_thread(scan_once, app)
        except Exception:
            logging.getLogger(__name__).warning('Recruitment work detection failed; retrying next interval')
        try:
            await asyncio.wait_for(stop.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass
