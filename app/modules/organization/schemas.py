from typing import Literal
from pydantic import Field
from app.core.schemas import Input


class UnitCreate(Input):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["legal_entity", "department", "location"]
    parent_id: str | None = None


class PositionCreate(Input):
    title: str = Field(min_length=1, max_length=200)
    unit_id: str
    capacity: int = Field(ge=1, le=10000)
    manager_id: str | None = None
