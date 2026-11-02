"""Offline coverage for bounded, same-provider Gemini failover."""
from types import SimpleNamespace

import httpx
import pytest
from openai import (
    APIConnectionError, APITimeoutError, AuthenticationError, BadRequestError,
    InternalServerError, NotFoundError, PermissionDeniedError, RateLimitError,
)

import config
import main
import summarizer

PRIMARY = "gemini-3.6-flash"
FALLBACK = "gemini-3.5-flash-lite"
NEWS = [{"title": "新闻", "link": "https://example.com/news", "source": "源"}]
OUTPUT = "HEADLINE: 标题\nTAGS: AI治理\n---\n## 今日要闻\n正文"


def response(content=OUTPUT, choices=True):
    return SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=content))]
        if choices else [], model="reported-model", usage=None,
    )


def api_error(status):
    classes = {400: BadRequestError, 401: AuthenticationError, 403: PermissionDeniedError,
               404: NotFoundError, 429: RateLimitError}
    return classes.get(status, InternalServerError)(
        "provider error", body=None,
        response=httpx.Response(status, request=httpx.Request("POST", "https://example.com")),
    )


@pytest.fixture
def fake_api(monkeypatch):
    outcomes, calls, sleeps, clients = [], [], [], []

    def create(**kwargs):
        calls.append(kwargs)
        if not outcomes:
            pytest.fail("Unexpected extra model request")
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def client(**kwargs):
        clients.append(kwargs)
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr(summarizer, "AI_MODEL", PRIMARY)
    monkeypatch.setattr(summarizer, "AI_FALLBACK_MODEL", FALLBACK)
    monkeypatch.setattr(summarizer, "AI_BASE_URL", config.GEMINI_OPENAI_BASE_URL)
    monkeypatch.setattr(summarizer, "AI_API_KEY", "test-only-key")
    monkeypatch.setattr(summarizer, "OpenAI", client)
    monkeypatch.setattr(summarizer.time, "sleep", sleeps.append)
    return SimpleNamespace(outcomes=outcomes, calls=calls, sleeps=sleeps, clients=clients)


@pytest.mark.parametrize("primary_failures", [0, 1])
def test_primary_success_never_calls_fallback(fake_api, primary_failures):
    fake_api.outcomes.extend([api_error(503)] * primary_failures + [response()])
    assert summarizer.generate_report(NEWS)["headline"] == "标题"
    assert [call["model"] for call in fake_api.calls] == [PRIMARY] * (primary_failures + 1)
    assert fake_api.sleeps == [60] * primary_failures


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retryable_status_switches_once_with_identical_input(fake_api, status, caplog):
    fake_api.outcomes.extend([api_error(status), api_error(status), response()])
    report = summarizer.generate_report(NEWS, previous_context="上期事实")
    assert report["content"] == "## 今日要闻\n正文"
    assert [call["model"] for call in fake_api.calls] == [PRIMARY, PRIMARY, FALLBACK]
    assert fake_api.sleeps == [60]
    assert len(fake_api.clients) == 1
    assert fake_api.clients[0] == {
        "base_url": config.GEMINI_OPENAI_BASE_URL, "api_key": "test-only-key",
        "timeout": summarizer.AI_TIMEOUT, "max_retries": 0,
    }
    assert all(call["messages"] == fake_api.calls[0]["messages"] for call in fake_api.calls)
    assert all(call["max_tokens"] == summarizer.AI_MAX_TOKENS for call in fake_api.calls)
    assert "上期事实" in fake_api.calls[-1]["messages"][1]["content"]
    assert "switching to fallback=gemini-3.5-flash-lite" in caplog.text
    assert "test-only-key" not in caplog.text


@pytest.mark.parametrize("error_class", [APIConnectionError, APITimeoutError])
def test_network_errors_can_switch_model(fake_api, error_class):
    error = error_class(request=httpx.Request("POST", "https://example.com"))
    fake_api.outcomes.extend([error, error, response()])
    summarizer.generate_report(NEWS)
    assert [call["model"] for call in fake_api.calls] == [PRIMARY, PRIMARY, FALLBACK]
    assert fake_api.sleeps == [60]


@pytest.mark.parametrize("recovers", [True, False])
def test_total_budget_is_four_calls_and_two_waits(fake_api, recovers):
    primary_error = api_error(503)
    fallback_error = api_error(429)
    fake_api.outcomes.extend([primary_error, primary_error, fallback_error,
                              response() if recovers else fallback_error])
    if recovers:
        summarizer.generate_report(NEWS)
    else:
        with pytest.raises(RateLimitError) as caught:
            summarizer.generate_report(NEWS)
        assert caught.value is fallback_error
        assert caught.value.__context__ is primary_error
    assert [call["model"] for call in fake_api.calls] == [PRIMARY, PRIMARY, FALLBACK, FALLBACK]
    assert fake_api.sleeps == [60, 60]


@pytest.mark.parametrize("status", [400, 401, 403, 404])
@pytest.mark.parametrize("on_fallback", [False, True])
def test_permanent_errors_are_never_retried_or_masked(fake_api, status, on_fallback):
    transient = api_error(503)
    permanent = api_error(status)
    fake_api.outcomes.extend(([transient, transient] if on_fallback else []) + [permanent])
    with pytest.raises(type(permanent)) as caught:
        summarizer.generate_report(NEWS)
    assert caught.value is permanent
    assert len(fake_api.calls) == (3 if on_fallback else 1)
    assert fake_api.sleeps == ([60] if on_fallback else [])


@pytest.mark.parametrize("invalid_response", [response(None), response("   "), response(choices=False),
                                               response("HEADLINE: 标题\nTAGS: AI治理\n---")])
@pytest.mark.parametrize("on_fallback", [False, True])
def test_invalid_outputs_do_not_retry_or_trigger_fallback(fake_api, invalid_response, on_fallback):
    fake_api.outcomes.extend(([api_error(503)] * 2 if on_fallback else []) + [invalid_response])
    with pytest.raises(RuntimeError):
        summarizer.generate_report(NEWS)
    assert len(fake_api.calls) == (3 if on_fallback else 1)
    assert fake_api.sleeps == ([60] if on_fallback else [])


@pytest.mark.parametrize("fallback", ["", PRIMARY])
def test_disabled_or_duplicate_fallback_preserves_original_budget(fake_api, monkeypatch, fallback):
    monkeypatch.setattr(summarizer, "AI_FALLBACK_MODEL", fallback)
    fake_api.outcomes.extend([api_error(503)] * 4)
    with pytest.raises(InternalServerError):
        summarizer.generate_report(NEWS)
    assert [call["model"] for call in fake_api.calls] == [PRIMARY] * 4
    assert fake_api.sleeps == [60, 300, 900]


@pytest.mark.parametrize("attribute,value", [
    ("AI_BASE_URL", "https://openrouter.ai/api/v1"),
    ("AI_BASE_URL", "https://generativelanguage.googleapis.com.evil.example/v1beta/openai/"),
    ("AI_MODEL", "other-provider/model"),
    ("AI_FALLBACK_MODEL", "gemini-a,gemini-b"),
    ("AI_FALLBACK_MODEL", "other-provider/model"),
])
def test_invalid_config_fails_before_client_creation(fake_api, monkeypatch, attribute, value):
    monkeypatch.setattr(summarizer, attribute, value)
    with pytest.raises(ValueError, match="AI_FALLBACK_MODEL requires"):
        summarizer.generate_report(NEWS)
    assert fake_api.clients == []
    assert fake_api.calls == []


def test_official_endpoint_without_trailing_slash_is_supported(fake_api, monkeypatch):
    monkeypatch.setattr(summarizer, "AI_BASE_URL", config.GEMINI_OPENAI_BASE_URL.rstrip("/"))
    fake_api.outcomes.extend([api_error(503), api_error(503), response()])
    summarizer.generate_report(NEWS)
    assert fake_api.calls[-1]["model"] == FALLBACK


def test_current_gemini_models_omit_deprecated_sampling_parameter(fake_api):
    fake_api.outcomes.extend([api_error(503), api_error(503), response()])
    summarizer.generate_report(NEWS)
    assert all("temperature" not in call for call in fake_api.calls)


@pytest.mark.parametrize("model,base_url", [
    ("gemini-2.5-flash", config.GEMINI_OPENAI_BASE_URL),
    (PRIMARY, "https://other.example/v1"),
])
def test_other_models_or_providers_preserve_temperature(fake_api, monkeypatch, model, base_url):
    monkeypatch.setattr(summarizer, "AI_FALLBACK_MODEL", "")
    monkeypatch.setattr(summarizer, "AI_MODEL", model)
    monkeypatch.setattr(summarizer, "AI_BASE_URL", base_url)
    fake_api.outcomes.append(response())
    summarizer.generate_report(NEWS)
    assert fake_api.calls[0]["temperature"] == summarizer.AI_TEMPERATURE


@pytest.mark.parametrize("outcome", ["success", "exhausted", "publish_failure", "skipped"])
def test_pipeline_never_repeats_publication_or_notifications(fake_api, monkeypatch, outcome):
    publications, notifications = [], []
    fake_api.outcomes.extend([api_error(503)] * 3 + [
        api_error(503) if outcome == "exhausted" else response()])

    def publish(report):
        publications.append(report)
        if outcome == "publish_failure":
            raise RuntimeError("publisher failed")
        return {"url": "https://notion.so/page", "skipped": outcome == "skipped"}

    def sleep(delay):
        assert not publications and not notifications
        fake_api.sleeps.append(delay)

    monkeypatch.setattr(main, "fetch_news", lambda: NEWS)
    monkeypatch.setattr(main, "get_previous_report_context", lambda: None)
    monkeypatch.setattr(main, "generate_report", summarizer.generate_report)
    monkeypatch.setattr(main, "push_to_notion", publish)
    monkeypatch.setattr(main, "notify", lambda title, description="": notifications.append(title))
    monkeypatch.setattr(summarizer.time, "sleep", sleep)
    if outcome in {"exhausted", "publish_failure"}:
        with pytest.raises(SystemExit) as caught:
            main.main()
        assert caught.value.code == 1
    else:
        main.main()
    assert len(publications) == (0 if outcome == "exhausted" else 1)
    assert len(notifications) == 1
    marker = {"success": "✅", "skipped": "⏭️", "exhausted": "❌", "publish_failure": "❌"}
    assert notifications[0].startswith(marker[outcome])
    assert len(fake_api.calls) == 4
    assert fake_api.sleeps == [60, 60]


@pytest.mark.parametrize("recovers", [True, False])
def test_real_openai_sdk_with_offline_transport_has_no_hidden_requests(fake_api, monkeypatch, recovers):
    """Verify actual pinned-SDK exception mapping and max_retries=0 offline."""
    import json
    from openai import OpenAI

    requests = []
    statuses = [503, 503, 429, 200 if recovers else 503]

    def handle(request):
        requests.append(request)
        if not statuses:
            pytest.fail("SDK made an unexpected extra HTTP request")
        status = statuses.pop(0)
        payload = {"error": {"message": "temporary failure", "code": status}}
        if status == 200:
            payload = {"id": "test", "object": "chat.completion", "created": 0,
                       "model": FALLBACK, "choices": [{"index": 0, "finish_reason": "stop",
                       "message": {"role": "assistant", "content": OUTPUT}}]}
        return httpx.Response(status, json=payload)

    with httpx.Client(transport=httpx.MockTransport(handle)) as http_client:
        monkeypatch.setattr(summarizer, "OpenAI", lambda **kwargs: OpenAI(
            **kwargs, http_client=http_client))
        if recovers:
            assert summarizer.generate_report(NEWS)["headline"] == "标题"
        else:
            with pytest.raises(InternalServerError):
                summarizer.generate_report(NEWS)
    assert len(requests) == 4
    assert all(str(request.url) == config.GEMINI_OPENAI_BASE_URL + "chat/completions"
               for request in requests)
    assert all(request.headers["authorization"] == "Bearer test-only-key" for request in requests)
    payloads = [json.loads(request.content) for request in requests]
    assert [payload["model"] for payload in payloads] == [PRIMARY, PRIMARY, FALLBACK, FALLBACK]
    assert all(payload["messages"] == payloads[0]["messages"] for payload in payloads)
    assert all("temperature" not in payload for payload in payloads)
    assert fake_api.sleeps == [60, 60]
