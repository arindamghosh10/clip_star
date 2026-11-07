import json
import subprocess
from types import SimpleNamespace

import httpx
import pytest

from clipstar.config import get_settings
from clipstar.engines import hosted_stt
from clipstar.engines.hosted_stt import AssemblyAIEngine, DeepgramEngine, segments_from_words
from clipstar.errors import PermanentError, RetryableError

CTX = SimpleNamespace(check=lambda: None)


@pytest.fixture
def wav(tmp_path):
    p = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=duration=1", "-ar", "16000", "-ac", "1", "-y", str(p)], check=True)
    return p


@pytest.fixture
def fake():
    calls = []

    def install(handler):
        def h(req):
            calls.append(req)
            return handler(req)

        hosted_stt.set_transport(httpx.MockTransport(h))
        return calls

    yield install
    hosted_stt.set_transport(None)


def test_segments_split_on_speaker_and_sentence():
    w = [(0, 0.4, "Hi", "Speaker 1"), (0.5, 0.9, "there.", "Speaker 1"), (1.0, 1.3, "Yes", "Speaker 2"), (1.4, 1.8, "really", "Speaker 2")]
    segs = segments_from_words(w)
    assert [(s.text, s.speaker) for s in segs] == [("Hi there.", "Speaker 1"), ("Yes really", "Speaker 2")]


def test_deepgram(fake, wav, client, monkeypatch):
    client.get("/api/workspace")
    monkeypatch.setattr(get_settings(), "deepgram_api_key", "dg_key")
    body = {"results": {"channels": [{"detected_language": "en", "alternatives": [{"words": [
        {"word": "check", "punctuated_word": "Check", "start": 0.1, "end": 0.4, "speaker": 0},
        {"word": "your", "punctuated_word": "your", "start": 0.4, "end": 0.6, "speaker": 0},
        {"word": "lease", "punctuated_word": "lease.", "start": 0.6, "end": 0.9, "speaker": 0},
        {"word": "agreed", "punctuated_word": "Agreed!", "start": 1.2, "end": 1.6, "speaker": 1},
    ]}]}]}}
    calls = fake(lambda r: httpx.Response(200, json=body))
    t = DeepgramEngine().transcribe(CTX, wav, 2.0, lambda p: None)
    req = calls[0]
    assert req.headers["authorization"] == "Token dg_key" and req.url.params["diarize"] == "true" and req.url.params["model"] == "nova-3"
    assert [(s.text, s.speaker) for s in t.segments] == [("Check your lease.", "Speaker 1"), ("Agreed!", "Speaker 2")]
    assert t.language == "en" and t.engine == "deepgram"
    fake(lambda r: httpx.Response(401, json={"err_msg": "bad key"}))
    with pytest.raises(PermanentError) as e:
        DeepgramEngine().transcribe(CTX, wav, 2.0, lambda p: None)
    assert "rejected the API key" in e.value.user_message


def test_assemblyai_polls_and_converts_ms(fake, wav, client, monkeypatch):
    client.get("/api/workspace")
    monkeypatch.setattr(get_settings(), "assemblyai_api_key", "aai_key")
    monkeypatch.setattr(AssemblyAIEngine, "POLL_S", 0)
    states = iter(["queued", "processing", "completed"])

    def h(req):
        if req.url.path == "/v2/upload":
            return httpx.Response(200, json={"upload_url": "https://cdn.assemblyai.com/upload/x"})
        if req.url.path == "/v2/transcript" and req.method == "POST":
            return httpx.Response(200, json={"id": "t1", "status": "queued"})
        st = next(states)
        if st != "completed":
            return httpx.Response(200, json={"id": "t1", "status": st})
        return httpx.Response(200, json={"id": "t1", "status": "completed", "language_code": "en_us", "words": [
            {"text": "Hello", "start": 100, "end": 400, "speaker": "A"}, {"text": "everyone.", "start": 400, "end": 900, "speaker": "A"},
            {"text": "Thanks.", "start": 1500, "end": 1900, "speaker": "B"},
        ]})

    calls = fake(h)
    t = AssemblyAIEngine().transcribe(CTX, wav, 2.0, lambda p: None)
    sub = json.loads(calls[1].content)
    assert calls[0].headers["authorization"] == "aai_key" and sub["speaker_labels"] is True and sub["speech_models"] == ["universal"]
    assert [(s.text, s.speaker, s.start) for s in t.segments] == [("Hello everyone.", "Speaker A", 0.1), ("Thanks.", "Speaker B", 1.5)]
    states2 = iter(["error"])
    fake(lambda r: httpx.Response(200, json={"upload_url": "u"}) if r.url.path == "/v2/upload" else httpx.Response(200, json={"id": "t2", "status": next(states2, "error"), "error": "audio too short"}))
    with pytest.raises(PermanentError) as e:
        AssemblyAIEngine().transcribe(CTX, wav, 2.0, lambda p: None)
    assert "audio too short" in e.value.user_message


def test_busy_provider_retries(fake, wav, client, monkeypatch):
    client.get("/api/workspace")
    monkeypatch.setattr(get_settings(), "deepgram_api_key", "k")
    fake(lambda r: httpx.Response(503))
    with pytest.raises(RetryableError):
        DeepgramEngine().transcribe(CTX, wav, 2.0, lambda p: None)
    assert DeepgramEngine().check().ok and not AssemblyAIEngine().check().ok
