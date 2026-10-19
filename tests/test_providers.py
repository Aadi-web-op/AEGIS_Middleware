import json

import httpx
import pytest

from app.providers.base import LLMProvider, ProviderError
from app.providers.factory import (
    ProviderSpec,
    ProvidersConfig,
    build_provider,
    load_providers_config,
)
from app.providers.fake import FakeProvider
from app.providers.fallback import FallbackProvider
from app.providers.openai_compat import OpenAICompatibleProvider


def ok_handler(request):
    return httpx.Response(200, json={"choices": [{"message": {"content": "  hello  "}}]})


def make_provider(handler, api_key="secret"):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAICompatibleProvider("test", "http://fake/v1/", "m1", api_key=api_key, client=client)


# ---- the interface and the fake ----

def test_cannot_instantiate_abstract_provider():
    with pytest.raises(TypeError):
        LLMProvider()


def test_fake_provider_replays_responses_and_records_prompts():
    fake = FakeProvider(["a", "b"])
    assert fake.generate("p1").text == "a"
    assert fake.generate("p2").text == "b"
    assert fake.generate("p3").text == "b"
    assert fake.prompts == ["p1", "p2", "p3"]


# ---- the OpenAI-compatible provider (no real network) ----

def test_parses_and_trims_the_reply():
    result = make_provider(ok_handler).generate("Q?")
    assert result.text == "hello"
    assert result.provider == "test"
    assert result.fallback_used is False


def test_sends_the_expected_request():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return ok_handler(request)

    make_provider(handler).generate("Q?", system="Be brief.", max_tokens=50)
    assert seen["url"] == "http://fake/v1/chat/completions"
    assert seen["auth"] == "Bearer secret"
    body = seen["body"]
    assert body["model"] == "m1"
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == 50
    assert body["messages"] == [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "Q?"},
    ]


def test_no_auth_header_without_a_key():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return ok_handler(request)

    make_provider(handler, api_key=None).generate("Q?")
    assert seen["auth"] is None


def test_error_status_becomes_provider_error():
    def handler(request):
        return httpx.Response(429, json={"error": "rate limited"})

    with pytest.raises(ProviderError, match="429"):
        make_provider(handler).generate("Q?")


def test_network_failure_becomes_provider_error():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(ProviderError):
        make_provider(handler).generate("Q?")


def test_unexpected_reply_shape_becomes_provider_error():
    def handler(request):
        return httpx.Response(200, json={"unexpected": 1})

    with pytest.raises(ProviderError, match="unexpected response format"):
        make_provider(handler).generate("Q?")


def test_empty_reply_becomes_provider_error():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "   "}}]})

    with pytest.raises(ProviderError, match="empty"):
        make_provider(handler).generate("Q?")


def test_error_message_never_leaks_the_key_or_body():
    def handler(request):
        return httpx.Response(500, text="server says secret")

    with pytest.raises(ProviderError) as info:
        make_provider(handler).generate("Q?")
    assert "secret" not in str(info.value)


# ---- the fallback chain ----

def test_fallback_uses_the_second_provider_when_the_first_fails():
    primary = FakeProvider(name="primary", fail=True)
    backup = FakeProvider(["from backup"], name="backup")
    result = FallbackProvider([primary, backup]).generate("Q?")
    assert result.text == "from backup"
    assert result.provider == "backup"
    assert result.fallback_used is True


def test_fallback_does_not_touch_the_backup_when_the_first_works():
    primary = FakeProvider(["from primary"], name="primary")
    backup = FakeProvider(name="backup")
    result = FallbackProvider([primary, backup]).generate("Q?")
    assert result.provider == "primary"
    assert result.fallback_used is False
    assert backup.prompts == []


def test_fallback_raises_when_every_provider_fails():
    chain = FallbackProvider([FakeProvider(name="a", fail=True), FakeProvider(name="b", fail=True)])
    with pytest.raises(ProviderError) as info:
        chain.generate("Q?")
    assert "a" in str(info.value) and "b" in str(info.value)


def test_fallback_needs_at_least_one_provider():
    with pytest.raises(ValueError):
        FallbackProvider([])


# ---- building from config ----

def spec(name, model="some-model", env=None):
    return ProviderSpec(name=name, base_url="http://x/v1", model=model, api_key_env=env)


def test_provider_with_a_missing_key_is_skipped(monkeypatch):
    monkeypatch.delenv("AEGIS_TEST_KEY", raising=False)
    config = ProvidersConfig(chain=[spec("cloud", env="AEGIS_TEST_KEY"), spec("local")])
    provider = build_provider(config)
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.name == "local"


def test_two_usable_providers_are_chained(monkeypatch):
    monkeypatch.setenv("AEGIS_TEST_KEY", "k")
    config = ProvidersConfig(chain=[spec("cloud", env="AEGIS_TEST_KEY"), spec("local")])
    provider = build_provider(config)
    assert isinstance(provider, FallbackProvider)
    assert [p.name for p in provider.providers] == ["cloud", "local"]


def test_no_usable_provider_raises():
    config = ProvidersConfig(chain=[spec("local", model="REPLACE_WITH_LOCAL_MODEL")])
    with pytest.raises(ProviderError):
        build_provider(config)


def test_default_providers_file_loads():
    assert len(load_providers_config().chain) >= 1
    