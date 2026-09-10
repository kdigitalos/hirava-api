"""Commit each API transaction before its response can be sent."""
from fastapi import APIRouter as FastAPIRouter
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool


class TransactionRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            db = request.app.state.sessions()
            request.state.db = db
            try:
                response = await original(request)
                await run_in_threadpool(db.commit)
                return response
            except Exception:
                await run_in_threadpool(db.rollback)
                raise
            finally:
                await run_in_threadpool(db.close)

        return handle


class APIRouter(FastAPIRouter):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("route_class", TransactionRoute)
        super().__init__(*args, **kwargs)
