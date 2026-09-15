from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Role = Literal["admin", "hr", "recruiter", "manager", "interviewer", "employee", "candidate"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Login(Input):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserCreate(Input):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    role: Role
    password: str | None = Field(default=None, min_length=12, max_length=128)
    auth_subject: str | None = Field(default=None, min_length=1, max_length=255)


class UserUpdate(Input):
    active: bool


class EmployeeLinkUpdate(Input):
    employee_id: str | None = Field(default=None, min_length=1, max_length=100)
    expected_version: int = Field(ge=1)


class Decision(Input):
    reason: str = Field(min_length=3, max_length=2000)


class PolicyCreate(Input):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=50000)
