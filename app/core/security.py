import hashlib
import hmac
import secrets
from datetime import timedelta
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import User
from app.data.database import get_db, utcnow

bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 600000).hex()
    return f"pbkdf2_sha256$600000${salt}${digest}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        # Spend comparable work for nonexistent users.
        hash_password(password)
        return False
    try:
        algorithm, iterations, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def issue_token(user, settings):
    now = utcnow()
    return jwt.encode({
        "sub": user.id, "customer_id": user.customer_id, "ver": user.token_version,
        "iat": now, "exp": now + timedelta(minutes=settings.token_minutes),
        "iss": "hirava-api-local", "aud": "hirava-api", "jti": secrets.token_hex(16),
    }, settings.jwt_secret.get_secret_value(), algorithm="HS256")


@lru_cache(maxsize=8)
def jwks_client(domain):
    return jwt.PyJWKClient(f"https://{domain}/.well-known/jwks.json", timeout=5)


def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                 db: Session = Depends(get_db)) -> User:
    unauthorized = HTTPException(401, "Invalid or expired credentials", headers={"WWW-Authenticate": "Bearer"})
    if credentials is None:
        raise unauthorized
    settings = request.app.state.settings
    try:
        if settings.auth_mode == "local":
            claims = jwt.decode(credentials.credentials, settings.jwt_secret.get_secret_value(),
                                algorithms=["HS256"], audience="hirava-api", issuer="hirava-api-local",
                                options={"require": ["exp", "iat", "sub", "customer_id", "ver"]})
            if claims["customer_id"] != settings.customer_id:
                raise unauthorized
            query = select(User).where(User.id == claims["sub"], User.token_version == claims["ver"])
        else:
            key = jwks_client(settings.auth0_domain).get_signing_key_from_jwt(credentials.credentials)
            claims = jwt.decode(credentials.credentials, key.key, algorithms=["RS256"],
                                audience=settings.auth0_audience, issuer=f"https://{settings.auth0_domain}/",
                                options={"require": ["exp", "iat", "sub"]})
            query = select(User).where(User.auth_subject == claims["sub"])
        user = db.scalar(query.where(User.customer_id == settings.customer_id, User.active.is_(True)))
        if user is None:
            raise unauthorized
        return user
    except jwt.PyJWTError:
        raise unauthorized from None


def require(*roles, module=None):
    def dependency(request: Request, user: User = Depends(current_user)):
        if module and not getattr(request.app.state.settings, f"{module}_enabled"):
            raise HTTPException(403, f"{module.upper()} module is disabled")
        if user.role not in roles and user.role != "admin":
            raise HTTPException(403, "Insufficient permissions")
        return user
    return dependency
