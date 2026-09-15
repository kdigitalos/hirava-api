from datetime import date
from decimal import Decimal
from typing import Literal
from fastapi import Depends, HTTPException, Query, Request
from pydantic import Field, field_validator
from sqlalchemy.orm import Session
from app.core.routing import APIRouter
from app.core.schemas import Input
from app.core.models import Document, User
from app.core.security import require
from app.core.service import audit, find, rows, view, state_is
from app.data.database import get_db
from .models import ExpenseClaim

router = APIRouter(prefix="/hrms/claims", tags=["Reimbursements"])
access = require("hr", "manager", "employee", module="hrms")


class ClaimInput(Input):
    category: str = Field(min_length=1, max_length=100)
    expense_type: str = Field(min_length=1, max_length=150)
    expense_date: date
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    currency: str = Field(pattern="^[A-Z]{3}$")
    description: str = Field(min_length=3, max_length=5000)
    receipt_id: str | None = None

    @field_validator("expense_date")
    @classmethod
    def actual_expense(cls, value):
        if value > date.today():
            raise ValueError("Expense date cannot be in the future")
        return value


class ClaimEdit(ClaimInput):
    expected_version: int = Field(ge=1)


class ClaimAction(Input):
    action: Literal["submit", "withdraw", "approve", "reject"]
    expected_version: int = Field(ge=1)
    reason: str = Field(default="", max_length=2000)


def own(record, user):
    if record.requester_id != user.id:
        raise HTTPException(403, "Only the requester can change this claim")


def version(record, expected):
    if record.version != expected:
        raise HTTPException(409, "Claim changed; reload before continuing")


def values(body, user, db):
    data = body.model_dump(exclude={"expected_version"})
    data["amount"] = format(body.amount, ".2f")
    if body.receipt_id:
        receipt = find(db, Document, body.receipt_id, user.customer_id)
        if receipt.owner_id != user.id or receipt.domain != "hrms":
            raise HTTPException(403, "Receipt must be your own HRMS document")
    return data


def result(db, record):
    data = view(record)
    data["requester_name"] = db.get(User, record.requester_id).name
    return data


@router.get("")
def list_claims(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                scope: Literal["mine", "review"] = "mine", user=Depends(access), db: Session = Depends(get_db)):
    if scope == "review" and user.role not in {"admin", "hr"}:
        raise HTTPException(403, "HR access required")
    conditions = [ExpenseClaim.status != "draft"] if scope == "review" else [ExpenseClaim.requester_id == user.id]
    return [result(db, row) for row in rows(db, ExpenseClaim, user.customer_id, offset, limit, *conditions)]


@router.post("", status_code=201)
def create_claim(body: ClaimInput, request: Request, user=Depends(access), db: Session = Depends(get_db)):
    record = ExpenseClaim(customer_id=user.customer_id, requester_id=user.id, **values(body, user, db))
    db.add(record)
    audit(db, user, "claim.created", record, request)
    return view(record)


@router.patch("/{record_id}")
def edit_claim(record_id: str, body: ClaimEdit, request: Request, user=Depends(access), db: Session = Depends(get_db)):
    record = find(db, ExpenseClaim, record_id, user.customer_id, lock=True)
    own(record, user)
    version(record, body.expected_version)
    state_is(record, "draft")
    for key, value in values(body, user, db).items():
        setattr(record, key, value)
    audit(db, user, "claim.edited", record, request)
    return view(record)


@router.post("/{record_id}/actions")
def claim_action(record_id: str, body: ClaimAction, request: Request, user=Depends(access), db: Session = Depends(get_db)):
    record = find(db, ExpenseClaim, record_id, user.customer_id, lock=True)
    version(record, body.expected_version)
    if body.action in {"submit", "withdraw"}:
        own(record, user)
        state_is(record, "draft" if body.action == "submit" else "pending")
        record.status = "pending" if body.action == "submit" else "draft"
    else:
        if user.role not in {"hr", "admin"} or record.requester_id == user.id:
            raise HTTPException(403, "A different HR or admin reviewer is required")
        state_is(record, "pending")
        if len(body.reason.strip()) < 3:
            raise HTTPException(422, "Record a review reason")
        record.status = "approved" if body.action == "approve" else "rejected"
        record.reviewed_by, record.decision_reason = user.id, body.reason
    audit(db, user, f"claim.{body.action}", record, request, reason=body.reason)
    return view(record)
