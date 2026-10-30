from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    environment: Literal["local", "test", "production"] = "local"
    database_url: str = f"sqlite:///{(ROOT / 'hirava.db').as_posix()}"
    customer_id: str = Field(default="local-customer", min_length=1, max_length=100, pattern="^[A-Za-z0-9][A-Za-z0-9_-]*$")
    auth_mode: Literal["local", "auth0"] = "local"
    jwt_secret: SecretStr = SecretStr("")
    token_minutes: int = Field(default=30, ge=1, le=120)
    auth0_domain: str = ""
    auth0_audience: str = ""
    rms_enabled: bool = True
    hrms_enabled: bool = True
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    storage_path: Path = ROOT / "storage"
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=50 * 1024 * 1024)
    expose_docs: bool = True

    @model_validator(mode="after")
    def validate_profile(self):
        if self.auth_mode == "local" and len(self.jwt_secret.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must contain at least 32 characters; run scripts/setup_local.py")
        if self.auth_mode == "auth0" and (
            not self.auth0_domain or not self.auth0_audience
            or "/" in self.auth0_domain or ":" in self.auth0_domain
        ):
            raise ValueError("Auth0 requires a bare AUTH0_DOMAIN hostname and AUTH0_AUDIENCE")
        if self.environment == "production":
            if self.auth_mode != "auth0" or not self.database_url.startswith("postgresql+psycopg://"):
                raise ValueError("Production requires Auth0 and PostgreSQL")
            if self.expose_docs or any(not origin.startswith("https://") for origin in self.cors_origins):
                raise ValueError("Production requires HTTPS CORS origins and EXPOSE_DOCS=false")
        return self
