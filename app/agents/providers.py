"""Shared provider selection and client creation for current and future agents.

Agents own their prompts, output schemas and capability checks. No provider fallback.
"""
from dataclasses import dataclass
from pydantic import SecretStr


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model: str
    api_key: SecretStr

    @property
    def ready(self):
        return bool(self.model and self.api_key.get_secret_value().strip())


def provider_config(settings, provider=None):
    provider = provider or settings.ai_provider or settings.ai_screening_provider
    if provider not in ("openai", "groq"):
        raise ValueError("Unsupported AI provider")
    model = getattr(settings, f"{provider}_model")
    if model is None:
        model = getattr(settings, f"{provider}_screening_model")
    return ProviderConfig(provider, model.strip(), getattr(settings, f"{provider}_api_key"))


def create_client(settings, config):
    if not config.ready:
        raise ValueError(f"Configure {config.provider.upper()}_API_KEY and {config.provider.upper()}_MODEL in the backend")
    from openai import OpenAI
    return OpenAI(api_key=config.api_key.get_secret_value(),
                  base_url="https://api.groq.com/openai/v1" if config.provider == "groq" else "https://api.openai.com/v1",
                  timeout=settings.ai_timeout_seconds, max_retries=0)
