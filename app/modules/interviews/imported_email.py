"""Explicit interview email action; content is plain text and recipients bounded."""
from fastapi import Depends, Request
from pydantic import EmailStr, Field
from app.core.compatibility_routing import APIRouter
from app.core.schemas import Input
from app.core.security import require
from app.core.imported_mail import send_interview

router = APIRouter(prefix='/api', tags=['Interview email compatibility'])


class EmailInput(Input):
    companyName: str = Field(min_length=1, max_length=255)
    duration: str | int
    emailDes: str = Field(default='', max_length=10000)
    interviewDate: str = Field(min_length=1, max_length=100)
    interviewTime: str = Field(min_length=1, max_length=100)
    interviewType: str = Field(default='', max_length=100)
    meetingPlatform: str = Field(default='', max_length=1000)
    panelMembers: str | list[str] = Field(default='', max_length=1000)
    participants: EmailStr | list[EmailStr] = Field(max_length=100)


@router.post('/sendEmails', status_code=202)
def send(body: EmailInput, request: Request, user=Depends(require('recruiter', module='rms'))):
    recipients = body.participants if isinstance(body.participants, list) else [body.participants]
    recipients = list(dict.fromkeys([user.email, *(str(value) for value in recipients)]))
    content = '\n'.join(f'{key}: {value}' for key, value in body.model_dump(exclude={'participants'}).items())
    send_interview(request.app.state.settings, recipients, content)
    return {'message': 'Email provider accepted the invitation request. Inbox delivery is not confirmed.', 'status': 'accepted_by_provider'}
