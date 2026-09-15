from datetime import date
from decimal import Decimal
import json
from typing import Annotated, Literal
from pydantic import EmailStr, Field, JsonValue, model_validator
from app.core.schemas import Input


Money = Annotated[Decimal, Field(ge=0, max_digits=16, decimal_places=2)]


class JobDetails(Input):
    company_name: str = Field(default="", max_length=255)
    department: str = Field(default="", max_length=255)
    location: str = Field(default="", max_length=2000)
    job_type: str = Field(default="", max_length=100)
    work_mode: str = Field(default="", max_length=100)
    recruiter_id: str | None = Field(default=None, min_length=1, max_length=36)
    hiring_due_date: date | None = None
    date_opened: date | None = None
    target_date: date | None = None
    job_link: str = Field(default="", max_length=2000)
    budget: Money | None = None
    salary_min: Money | None = None
    salary_max: Money | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    no_of_openings: int = Field(default=1, ge=1, le=100000)
    required_skills: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(default_factory=list, max_length=200)
    hiring_flow: str = Field(default="", max_length=20000)
    extra_fields: JsonValue = Field(default_factory=dict)
    logo: Literal["google", "facebook", "default"] = "default"

    @model_validator(mode="after")
    def validate_details(self):
        if self.salary_min is not None and self.salary_max is not None and self.salary_max < self.salary_min:
            raise ValueError("Maximum salary cannot be less than minimum salary")
        if any(value is not None for value in (self.budget, self.salary_min, self.salary_max)) and not self.currency:
            raise ValueError("Currency is required for monetary amounts")
        if len(json.dumps(self.extra_fields, ensure_ascii=False, allow_nan=False).encode('utf-8')) > 65536:
            raise ValueError("Custom job fields exceed 64 KiB")
        if self.job_link and not self.job_link.startswith(('https://', 'http://')):
            raise ValueError("Job link must use HTTP or HTTPS")
        return self


class RequisitionCreate(Input):
    position_id: str
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=20000)
    job_details: JobDetails = Field(default_factory=JobDetails)


class RequisitionUpdate(Input):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1, max_length=20000)
    job_details: JobDetails | None = None

    @model_validator(mode="after")
    def validate_change(self):
        changes = self.model_fields_set - {'expected_version'}
        if not changes or any(getattr(self, name) is None for name in changes):
            raise ValueError("Provide at least one non-null field to update")
        return self


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
