"""LLMRouter auth-mode selection: subscription OAuth (Bearer) vs API key."""

from types import SimpleNamespace

from dropagent.clients.llm.router import LLMRouter


def _settings(api_key: str = "", auth_token: str = "") -> SimpleNamespace:
    return SimpleNamespace(anthropic=SimpleNamespace(api_key=api_key, auth_token=auth_token))


def test_prefers_oauth_when_auth_token_set():
    router = LLMRouter(settings=_settings(api_key="sk-ignored", auth_token="oauth-token-xyz"))
    assert router._auth_mode == "oauth"
    # the Bearer/OAuth path must not fall back to x-api-key auth
    assert router.client.api_key in (None, "")


def test_uses_api_key_when_no_auth_token():
    router = LLMRouter(settings=_settings(api_key="sk-test", auth_token=""))
    assert router._auth_mode == "api_key"
