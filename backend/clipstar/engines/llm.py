"""Shared calls to AI providers that return JSON matching a schema.

Errors are translated into two kinds the stages understand:
- RetryableError: temporary (rate limit, network, server error) -> the job retries with backoff.
- EngineDeclined: retrying won't help (bad key, refusal, rejected request) -> use the free fallback.
"""

from __future__ import annotations

import json
import os

import httpx

from ..config import get_settings
from ..errors import RetryableError
from .base import Health


class EngineDeclined(Exception):
    """The provider can't do this request; the caller falls back to its free engine."""


def anthropic_key() -> str | None:
    return get_settings().anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")


def claude_health() -> Health:
    if not anthropic_key():
        return Health(False, "No Anthropic API key. Set CLIPSTAR_ANTHROPIC_API_KEY.")
    return Health(True, f"Model: {get_settings().claude_model}")


def claude_json(system: str, prompt: str, schema: dict, max_tokens: int = 16000) -> str:
    import anthropic

    st = get_settings()
    client = anthropic.Anthropic(api_key=anthropic_key(), timeout=300.0, max_retries=2)
    try:
        resp = client.beta.messages.create(
            model=st.claude_model,
            max_tokens=max_tokens,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # if the model declines, the API retries on a fallback model
            output_config={"effort": st.claude_effort, "format": {"type": "json_schema", "schema": schema}},
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.AuthenticationError as e:
        raise EngineDeclined("the API key was rejected") from e
    except anthropic.PermissionDeniedError as e:
        raise EngineDeclined("the API key doesn't have access to this model") from e
    except anthropic.BadRequestError as e:
        raise EngineDeclined(f"the request was rejected ({e.message[:200]})") from e
    except anthropic.RateLimitError as e:
        raise RetryableError(str(e), user_message="Claude rate limit reached; will retry.") from e
    except anthropic.APIConnectionError as e:
        raise RetryableError(str(e), user_message="Couldn't reach the Anthropic API; will retry.") from e
    except anthropic.APIStatusError as e:
        if e.status_code >= 500:
            raise RetryableError(str(e), user_message="The Anthropic API had a server error; will retry.") from e
        raise EngineDeclined(f"API error {e.status_code}") from e
    if resp.stop_reason == "refusal":
        raise EngineDeclined("the model declined this request")
    if resp.stop_reason == "max_tokens":
        raise EngineDeclined("the answer was cut off")
    return next((b.text for b in resp.content if b.type == "text"), "")


def ollama_health() -> Health:
    st = get_settings()
    try:
        r = httpx.get(f"{st.ollama_url}/api/tags", timeout=3)
        names = [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:
        return Health(False, f"Ollama isn't reachable at {st.ollama_url}.")
    if not any(n == st.ollama_model or n.split(":")[0] == st.ollama_model for n in names):
        return Health(False, f"Model '{st.ollama_model}' isn't pulled. Run: ollama pull {st.ollama_model}")
    return Health(True, f"Model: {st.ollama_model}")


def ollama_json(system: str, prompt: str, schema: dict) -> str:
    st = get_settings()
    try:
        r = httpx.post(
            f"{st.ollama_url}/api/chat",
            json={
                "model": st.ollama_model,
                "stream": False,
                "format": schema,
                "options": {"temperature": 0.2, "num_ctx": 32768},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            },
            timeout=900,
        )
    except httpx.HTTPError as e:
        raise RetryableError(str(e), user_message="Couldn't reach Ollama; will retry.") from e
    if r.status_code >= 500:
        raise RetryableError(r.text[:300], user_message="Ollama had an error; will retry.")
    if r.status_code >= 400:
        raise EngineDeclined(f"Ollama rejected the request ({r.text[:200]})")
    try:
        return r.json()["message"]["content"]
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        raise EngineDeclined("Ollama returned an unexpected response") from e
