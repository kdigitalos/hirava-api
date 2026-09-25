from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from fastapi import Depends, HTTPException, Query, Request
from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.core.compatibility_routing import APIRouter
from app.core.schemas import Input
from app.core.security import require
from app.core.service import audit, find, view
from app.data.database import get_db
from .engine import calculate, CalculationError
from .models import SalaryStructure

router = APIRouter(prefix="/api/payroll", tags=["Payroll"])
access = require("hr", module="hrms")


class Component(Input):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,39}$")
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["earning", "deduction", "employer"]
    formula: str = Field(min_length=1, max_length=300)


class Definition(Input):
    components: list[Component] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def valid_codes(self):
        codes = [item.code for item in self.components]
        if len(set(codes)) != len(codes) or set(codes) & {"GROSS", "MIN", "MAX", "ROUND", "CEILING", "FLOOR"}:
            raise ValueError("Component codes must be unique and cannot use reserved formula names")
        if not any(item.kind == "earning" for item in self.components):
            raise ValueError("Include at least one earnings component")
        return self


class Preview(Definition):
    monthly_gross: Decimal = Field(gt=0, le=999999999, max_digits=11, decimal_places=2)


class Create(Preview):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,39}$")
    name: str = Field(min_length=1, max_length=160)
    effective_from: date
    reason: str = Field(min_length=3, max_length=1000)


def preview(body):
    try:
        return calculate([item.model_dump() for item in body.components], body.monthly_gross)
    except CalculationError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/structures")
def structures(user=Depends(access), db=Depends(get_db)):
    return [view(row) for row in db.scalars(select(SalaryStructure).where(
        SalaryStructure.customer_id == user.customer_id).order_by(SalaryStructure.code, SalaryStructure.effective_from.desc()))]


@router.post("/preview")
def preview_structure(body: Preview, user=Depends(access)):
    return preview(body)


@router.post("/structures", status_code=201)
def create_structure(body: Create, request: Request, user=Depends(access), db=Depends(get_db)):
    preview(body)
    record = SalaryStructure(customer_id=user.customer_id, created_by=user.id,
        **body.model_dump(mode="json", exclude={"monthly_gross", "effective_from"}), effective_from=body.effective_from)
    db.add(record)
    try:
        audit(db, user, "payroll.structure.created", record, request, reason=body.reason,
              code=body.code, effective_from=body.effective_from.isoformat())
    except IntegrityError as exc:
        raise HTTPException(409, "This structure code already has a version starting on that date") from exc
    return view(record)


@router.post("/structures/{record_id}/preview")
def preview_saved(record_id: str, monthly_gross: Annotated[Decimal, Query(gt=0, le=999999999, max_digits=11, decimal_places=2)], as_of: date,
                  user=Depends(access), db=Depends(get_db)):
    record = find(db, SalaryStructure, record_id, user.customer_id)
    effective = db.scalar(select(SalaryStructure).where(SalaryStructure.customer_id == user.customer_id,
        SalaryStructure.code == record.code, SalaryStructure.effective_from <= as_of)
        .order_by(SalaryStructure.effective_from.desc()).limit(1))
    if effective is None:
        raise HTTPException(422, "No structure version is effective on this date")
    result = preview(Preview(components=effective.components, monthly_gross=monthly_gross))
    return {**result, "structure_id": effective.id, "effective_from": effective.effective_from}
