"""Bounded JSON requests and error keys used by retained frontend clients."""
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from app.core.routing import APIRouter as TransactionRouter, TransactionRoute


class CompatibilityRoute(TransactionRoute):
    max_body_bytes = 1024 * 1024
    def get_route_handler(self):
        transactional = super().get_route_handler()

        async def handle(request):
            try:
                if request.method in {"POST", "PUT", "PATCH"}:
                    body = bytearray()
                    async for chunk in request.stream():
                        body.extend(chunk)
                        if len(body) > self.max_body_bytes:
                            raise HTTPException(413, "The submitted form exceeds the size limit.")
                    request._body = bytes(body)
                return await transactional(request)
            except HTTPException as exc:
                # The transaction wrapper has already rolled back any failed writes.
                return JSONResponse(status_code=exc.status_code,
                    content={"detail": exc.detail, "message": exc.detail, "error": exc.detail}, headers=exc.headers)

        return handle


class APIRouter(TransactionRouter):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("route_class", CompatibilityRoute)
        super().__init__(*args, **kwargs)
