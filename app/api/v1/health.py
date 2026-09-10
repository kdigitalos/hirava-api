from typing import Literal

from app.core.routing import APIRouter
from fastapi import Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.data.database import get_db

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["hirava-api"] = "hirava-api"


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Process liveness only; does not assert database or provider readiness."""
    return HealthResponse()


@router.get("/ready")
def readiness(db: Session = Depends(get_db)):
    try:
        # Requires the migrated schema, rather than just a TCP connection.
        db.execute(text("SELECT version_num FROM alembic_version"))
        db.execute(text("SELECT id FROM users LIMIT 1"))
    except Exception:
        db.rollback()
        raise HTTPException(503, "Database migrations or connectivity unavailable") from None
    return {"status": "ready"}
