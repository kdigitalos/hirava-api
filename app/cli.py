"""Administrative operations require local shell access; no public bootstrap endpoint."""
import argparse
from getpass import getpass
from sqlalchemy import select
from app.core.config import Settings
from app.core.models import User
from app.core.schemas import UserCreate
from app.core.security import hash_password
from app.data import registry  # noqa: F401
from app.data.database import build_engine, session_factory


def main():
    parser = argparse.ArgumentParser(description="Hirava instance administration")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-admin")
    create.add_argument("--email", required=True)
    create.add_argument("--name", default="Local Administrator")
    create.add_argument("--auth-subject")
    args = parser.parse_args()
    settings = Settings()
    password = None
    if settings.auth_mode == "local":
        password = getpass("New administrator password (12+ characters): ")
        if password != getpass("Confirm password: "):
            parser.error("Passwords do not match")
    elif not args.auth_subject:
        parser.error("Auth0 mode requires --auth-subject")
    body = UserCreate(email=args.email, name=args.name, role="admin", password=password, auth_subject=args.auth_subject)
    engine = build_engine(settings.database_url)
    try:
        with session_factory(engine).begin() as db:
            if db.scalar(select(User.id).where(User.customer_id == settings.customer_id, User.email == str(body.email).lower())):
                parser.error("User already exists")
            db.add(User(customer_id=settings.customer_id, email=str(body.email).lower(), name=body.name,
                        role="admin", auth_subject=body.auth_subject,
                        password_hash=hash_password(body.password) if body.password else None))
        print("Administrator created. Sign in through /api/v1/auth/login or your Auth0 application.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
