"""Administrator invitations with persisted recovery and server-only Auth0 calls."""
import secrets
from datetime import timedelta, timezone
from uuid import uuid4

import httpx
from fastapi import Depends, HTTPException, Request
from pydantic import EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.routing import APIRouter
from app.core.schemas import Input, Role
from app.core.security import require
from app.core.models import AccountInvitation, User
from app.core.service import audit, find, view
from app.core.employee_access import set_employee_link
from app.data.database import get_db, utcnow

router = APIRouter(tags=["account invitations"])


class Invite(Input):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    role: Role
    employee_id: str | None = Field(default=None, min_length=1, max_length=100)


def configured(settings):
    return bool(settings.auth_mode == "auth0" and settings.auth0_domain and settings.auth0_mgmt_client_id
                and settings.auth0_mgmt_client_secret.get_secret_value() and settings.auth0_web_client_id)


class ProviderError(Exception):
    pass


class Auth0Provider:
    def __init__(self, settings):
        self.settings = settings
        self.base = f"https://{settings.auth0_domain}"

    def call(self, method, path, **kwargs):
        try:
            with httpx.Client(timeout=15, follow_redirects=False) as client:
                response = client.request(method, self.base + path, **kwargs)
            if not response.is_success:
                raise ProviderError("provider_rejected_request")
            return response
        except httpx.HTTPError:
            raise ProviderError("provider_unavailable") from None

    def identity(self, account, invitation):
        token = self.call("POST", "/oauth/token", json={"grant_type": "client_credentials",
            "client_id": self.settings.auth0_mgmt_client_id,
            "client_secret": self.settings.auth0_mgmt_client_secret.get_secret_value(),
            "audience": self.base + "/api/v2/"}).json().get("access_token")
        if not token:
            raise ProviderError("provider_invalid_response")
        headers = {"Authorization": f"Bearer {token}"}
        people = self.call("GET", "/api/v2/users-by-email", headers=headers, params={"email": account.email}).json()
        if not isinstance(people, list):
            raise ProviderError("provider_invalid_response")
        if people:
            matches = [p for p in people if p.get("email", "").lower() == account.email
                and any(i.get("connection") == self.settings.auth0_connection and i.get("provider") == "auth0"
                        for i in p.get("identities", []))]
            # The admin explicitly chose this email. Only a verified database
            # identity or this exact operation's recovery marker can be linked.
            if len(matches) != 1 or (matches[0].get("email_verified") is not True
                    and matches[0].get("app_metadata", {}).get("hirava_invitation_id") != invitation.id):
                raise ProviderError("existing_identity_requires_review")
            person = matches[0]
        else:
            person = self.call("POST", "/api/v2/users", headers=headers, json={
                "connection": self.settings.auth0_connection, "email": account.email, "name": account.name,
                "password": "Aa1!" + secrets.token_urlsafe(40), "email_verified": False, "verify_email": False,
                "app_metadata": {"hirava_invitation_id": invitation.id}}).json()
        if person.get("blocked"):
            raise ProviderError("provider_identity_blocked")
        subject = person.get("user_id")
        if not isinstance(subject, str) or not subject.startswith("auth0|") or len(subject) > 255:
            raise ProviderError("provider_invalid_response")
        return subject

    def send(self, account):
        # Auth0 sends its password-setup/reset template. A successful request
        # means accepted by Auth0, not confirmed inbox delivery.
        self.call("POST", "/dbconnections/change_password", json={
            "client_id": self.settings.auth0_web_client_id, "email": account.email,
            "connection": self.settings.auth0_connection})


def deliver(db, invitation_id, actor, settings, request):
    invitation = find(db, AccountInvitation, invitation_id, actor.customer_id, lock=True)
    account = find(db, User, invitation.user_id, actor.customer_id, lock=True)
    if invitation.status == "accepted_by_provider":
        return {"account": view(account), "invitation": view(invitation)}
    last = invitation.attempted_at
    if last and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if invitation.status == "processing" and last and last > utcnow() - timedelta(minutes=5):
        raise HTTPException(409, "Invitation is processing; wait before retrying")
    if account.auth_subject and not account.active:
        raise HTTPException(409, "Account is inactive; review its access before retrying")
    invitation.status, invitation.attempted_at, invitation.error_code = "processing", utcnow(), None
    db.commit()  # Persist recovery marker before any external write.
    try:
        invitation = find(db, AccountInvitation, invitation_id, actor.customer_id, lock=True)
        account = find(db, User, invitation.user_id, actor.customer_id, lock=True)
        provider = Auth0Provider(settings)
        if not account.auth_subject:
            subject = provider.identity(account, invitation)
            if db.scalar(select(User).where(User.auth_subject == subject, User.id != account.id)):
                raise ProviderError("identity_already_linked")
            account.auth_subject, account.active = subject, True
            if invitation.employee_id:
                set_employee_link(db, account, invitation.employee_id)
            audit(db, actor, "user.invitation_provisioned", account, request)
        db.commit()  # Identity/link must be durable before the email request.
        invitation = find(db, AccountInvitation, invitation_id, actor.customer_id, lock=True)
        account = find(db, User, invitation.user_id, actor.customer_id, lock=True)
        if not account.active:
            raise ProviderError("account_inactive")
        provider.send(account)
        invitation.status = "accepted_by_provider"
        audit(db, actor, "user.invitation_email_requested", account, request)
        db.commit()
    except (ProviderError, HTTPException, ValueError) as error:
        db.rollback()
        invitation = find(db, AccountInvitation, invitation_id, actor.customer_id, lock=True)
        invitation.status = "failed"
        invitation.error_code = str(error) if isinstance(error, ProviderError) else "employee_link_or_provider_response_failed"
        audit(db, actor, "user.invitation_failed", invitation, request, error_code=invitation.error_code)
        db.commit()
    account = find(db, User, invitation.user_id, actor.customer_id)
    return {"account": view(account), "invitation": view(invitation)}


@router.get("/account-invitations")
def invitations(request: Request, actor=Depends(require("admin")), db: Session = Depends(get_db)):
    records = db.scalars(select(AccountInvitation).where(AccountInvitation.customer_id == actor.customer_id)
                        .order_by(AccountInvitation.created_at.desc()).limit(100)).all()
    return {"configured": configured(request.app.state.settings), "invitations": [view(r) for r in records]}


@router.post("/account-invitations")
def invite(body: Invite, request: Request, actor=Depends(require("admin")), db: Session = Depends(get_db)):
    settings = request.app.state.settings
    if not configured(settings):
        raise HTTPException(503, "Invitations are not configured yet. Contact your system administrator.")
    if body.role == "candidate" and body.employee_id:
        raise HTTPException(422, "Candidates cannot be linked to employee records")
    email = str(body.email).lower()
    if db.scalar(select(User).where(User.customer_id == actor.customer_id, User.email == email)):
        raise HTTPException(409, "Account already exists; use its invitation status or employee link below")
    account = User(id=str(uuid4()), customer_id=actor.customer_id, name=body.name, email=email,
                   role=body.role, active=False)
    db.add(account)
    db.flush()
    if body.employee_id:
        if not settings.hrms_enabled:
            raise HTTPException(409, "Employee directory is unavailable")
        # Validate availability in a savepoint without granting access early.
        with db.begin_nested() as check:
            account.active = True
            set_employee_link(db, account, body.employee_id)
            check.rollback()
    invitation = AccountInvitation(customer_id=actor.customer_id, user_id=account.id, employee_id=body.employee_id)
    db.add(invitation)
    audit(db, actor, "user.invitation_requested", account, request, role=body.role, employee_id=body.employee_id)
    db.commit()
    return deliver(db, invitation.id, actor, settings, request)


@router.post("/account-invitations/{invitation_id}/retry")
def retry(invitation_id: str, request: Request, actor=Depends(require("admin")), db: Session = Depends(get_db)):
    if not configured(request.app.state.settings):
        raise HTTPException(503, "Invitations are not configured yet. Contact your system administrator.")
    return deliver(db, invitation_id, actor, request.app.state.settings, request)
