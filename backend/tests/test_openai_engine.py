import json

import httpx
import pytest

from clipstar.config import get_settings
from clipstar.engines import llm
from clipstar.engines.llm import EngineDeclined, openai_health, openai_json
from clipstar.errors import RetryableError


@pytest.fixture
def api(client, monkeypatch):
    client.get("/api/workspace")
    st = get_settings()
    monkeypatch.setattr(st, "openai_api_key", "sk-test")
    monkeypatch.setattr(st, "openai_model", "some-model")
    monkeypatch.setattr(st, "openai_price_input_per_mtok", 1.0)
    monkeypatch.setattr(st, "openai_price_output_per_mtok", 2.0)
    calls = []

    def install(handler):
        def h(req):
            calls.append(req)
            return handler(req)

        monkeypatch.setattr(llm, "_openai_transport", httpx.MockTransport(h))
        return calls

    return install


def ok(content='{"x": 1}', finish="stop", refusal=None):
    return lambda r: httpx.Response(200, json={"choices": [{"message": {"content": content, "refusal": refusal}, "finish_reason": finish}], "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 500_000}})


def test_request_shape_and_metering(api, client):
    calls = api(ok())
    assert openai_json("sys", "hi", {"type": "object"}) == '{"x": 1}'
    body = json.loads(calls[0].content)
    assert calls[0].url.path == "/v1/chat/completions" and calls[0].headers["authorization"] == "Bearer sk-test"
    assert body["model"] == "some-model" and body["response_format"]["type"] == "json_schema" and body["messages"][0] == {"role": "system", "content": "sys"}
    b = client.get("/api/admin/budget").json()
    assert b["by_engine"][0]["engine"] == "openai" and b["spent_usd"] == pytest.approx(2.0)


@pytest.mark.parametrize(
    "resp,exc,match",
    [
        (ok(refusal="no"), EngineDeclined, "declined"),
        (ok(finish="length"), EngineDeclined, "cut off"),
        (lambda r: httpx.Response(401, json={}), EngineDeclined, "key was rejected"),
        (lambda r: httpx.Response(429, json={"error": {"code": "insufficient_quota"}}), EngineDeclined, "out of credit"),
        (lambda r: httpx.Response(429, json={"error": {"code": "rate_limit"}}), RetryableError, ""),
        (lambda r: httpx.Response(503), RetryableError, ""),
    ],
)
def test_failures_fall_back_or_retry(api, resp, exc, match):
    api(resp)
    with pytest.raises(exc, match=match):
        openai_json("s", "p", {"type": "object"})


def test_needs_model_choice(monkeypatch):
    monkeypatch.setattr(get_settings(), "openai_api_key", "sk")
    monkeypatch.setattr(get_settings(), "openai_model", None)
    h = openai_health()
    assert not h.ok and "CLIPSTAR_OPENAI_MODEL" in h.message


def test_moment_engine_uses_openai(api):
    from clipstar.engines.moments_engines import OpenAIMomentEngine

    api(ok(content='{"moments": []}'))
    assert OpenAIMomentEngine().call("s", "p") == '{"moments": []}'
