from typing import Literal
from pydantic import EmailStr, Field
from app.core.schemas import Input


class RequisitionCreate(Input):
    position_id: str
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=20000)


class CandidateCreate(Input):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    consent: Literal[True]
    consent_notice: str = Field(min_length=1, max_length=100)


class ApplicationCreate(Input):
    candidate_id: str
    requisition_id: str


class ApplicationTransition(Input):
    status: Literal["screening", "interviewing", "selected", "rejected", "withdrawn"]
    reason: str = Field(min_length=3, max_length=2000)
