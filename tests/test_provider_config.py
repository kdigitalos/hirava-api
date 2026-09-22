import pytest
from app.core.config import Settings
from app.agents.providers import provider_config, create_client
from app.agents.application import provider_config as screening_config


def settings(**kwargs):
    return Settings(_env_file=None, jwt_secret="x" * 32, **kwargs)


def test_shared_selection_overrides_legacy_and_keeps_models_separate():
    config = settings(ai_provider="openai", ai_screening_provider="groq",
        openai_model="gpt-4.1-mini", openai_screening_model="old",
        groq_model="groq-model", openai_api_key="test-openai", groq_api_key="test-groq")
    assert screening_config(config) == ("openai", "gpt-4.1-mini", True)
    config.ai_provider = "groq"
    assert screening_config(config) == ("groq", "groq-model", True)
    assert "test-groq" not in repr(provider_config(config))


def test_legacy_and_no_fallback():
    config = settings(ai_screening_provider="groq", groq_screening_model="legacy",
                      openai_api_key="available", openai_model="other")
    selected = provider_config(config)
    assert selected.provider == "groq" and selected.model == "legacy"
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        create_client(config, selected)
    config.groq_model = " "
    assert provider_config(config).model == ""


@pytest.mark.parametrize("provider,url", [("openai", "https://api.openai.com/v1"),
                                         ("groq", "https://api.groq.com/openai/v1")])
def test_shared_client_uses_only_selected_credentials(monkeypatch, provider, url):
    captured = {}
    monkeypatch.setattr("openai.OpenAI", lambda **kwargs: captured.update(kwargs))
    config = settings(ai_provider=provider, openai_model="openai-model", groq_model="groq-model",
                      openai_api_key="test-openai", groq_api_key="test-groq")
    create_client(config, provider_config(config))
    assert captured["base_url"] == url
    assert captured["api_key"] == f"test-{provider}"
    assert captured["max_retries"] == 0
