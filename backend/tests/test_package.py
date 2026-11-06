import json

import pytest

from clipstar.engines.package_engines import ClaudePackageEngine, TemplatePackageEngine
from clipstar.engines.llm import EngineDeclined
from clipstar.pipeline.package import ALL_PLATFORMS, ClipContext, PackageSettings, check_copy, compose, finalize_copy, normalize_tag, smart_trim

CLIP = ClipContext(
    title="Nobody tells you this about rent",
    hook="NOBODY TELLS YOU",
    text="Nobody tells you this about rent? I lost forty dollars a month for three years because of the admin fee in my lease. Check your lease for the admin fee.",
    duration=42,
)


class Ctx:
    attempt = 1

    def progress(self, *a, **k):
        pass

    def check(self):
        pass


def test_helpers():
    assert normalize_tag("#Rent Tips!") == "RentTips"
    assert normalize_tag("##") == ""
    assert smart_trim("one two three four", 10) == "one two…"
    assert compose({"caption": "Hi", "hashtags": ["a", "b"]}, "x") == "Hi\n\n#a #b"


def test_templates_cover_every_platform_within_limits():
    st = PackageSettings(hashtags=["moneytips"], cta="Follow for part 2.")
    raw, _ = TemplatePackageEngine().write(Ctx(), CLIP, st)
    copy, pre, notes = finalize_copy(raw, CLIP, st)
    assert set(copy) == set(ALL_PLATFORMS) and all(p["ok"] for p in pre.values()), pre
    assert copy["youtube"]["title"] == CLIP.title and copy["youtube"]["hashtags"][0] == "moneytips"
    assert copy["instagram"]["hashtags"][0] == "moneytips" and "Follow for part 2." in copy["instagram"]["caption"]
    assert len(copy["threads"]["hashtags"]) <= 1 and copy["instagram"]["title"] == ""
    assert "admin" in copy["tiktok"]["hashtags"] or "lease" in copy["tiktok"]["hashtags"]


def test_limits_are_enforced_on_whatever_an_engine_returns():
    st = PackageSettings(platforms=["x", "youtube"])
    raw = {
        "x": {"title": "", "caption": "word " * 200, "hashtags": ["#One", "one", "two", "three", "four"]},
        "youtube": {"title": "T" * 300, "caption": "ok", "hashtags": []},
    }
    copy, pre, _ = finalize_copy(raw, CLIP, st)
    assert copy["x"]["hashtags"] == ["One", "two"]  # deduped, limited to 2
    assert len(compose(copy["x"], "x")) <= 280 and copy["x"]["caption"].endswith("…")
    assert len(copy["youtube"]["title"]) <= 100 and pre["x"]["ok"]


def test_banned_topic_in_copy_falls_back_to_template_and_long_clips_fail_preflight():
    st = PackageSettings(platforms=["x", "instagram"], banned_topics=["crypto"])
    raw = {"instagram": {"title": "", "caption": "Buy crypto now", "hashtags": ["crypto"]}}
    long_clip = ClipContext(**{**CLIP.__dict__, "duration": 170})
    copy, pre, notes = finalize_copy(raw, long_clip, st)
    assert "crypto" not in compose(copy["instagram"], "instagram").lower() and any("crypto" in n for n in notes)
    assert not pre["x"]["ok"] and "140s" in pre["x"]["problems"][0]


def test_check_copy_reports_without_changing():
    pre = check_copy({"x": {"title": "", "caption": "a" * 300, "hashtags": []}, "youtube": {"title": "", "caption": "", "hashtags": []}}, 30)
    assert not pre["x"]["ok"] and not pre["youtube"]["ok"] and "title is required" in pre["youtube"]["problems"][0].lower()


def _claude(monkeypatch, answers):
    e = ClaudePackageEngine()
    monkeypatch.setattr(e, "check", lambda: type("H", (), {"ok": True, "message": ""})())
    it = iter(answers)

    def call(system, prompt, schema):
        a = next(it)
        if isinstance(a, Exception):
            raise a
        return a

    monkeypatch.setattr(e, "call", call)
    return e


def test_ai_copy_partial_answer_is_filled_by_templates(monkeypatch):
    st = PackageSettings(platforms=["youtube", "tiktok"])
    e = _claude(monkeypatch, [json.dumps({"youtube": {"title": "Rent trap explained", "caption": "The fee nobody checks.", "hashtags": ["rent"]}, "tiktok": {"oops": 1}})])
    raw, notes = e.write(Ctx(), CLIP, st)
    copy, pre, _ = finalize_copy(raw, CLIP, st)
    assert copy["youtube"]["title"] == "Rent trap explained" and copy["tiktok"]["caption"]
    assert "tiktok" in notes[0]


def test_ai_copy_declined_uses_templates(monkeypatch):
    e = _claude(monkeypatch, [EngineDeclined("the model declined this request")])
    raw, notes = e.write(Ctx(), CLIP, PackageSettings())
    assert set(raw) == set(ALL_PLATFORMS) and "declined" in notes[0]


@pytest.fixture
def settings_body():
    return {"settings": {"clip_min_s": 8, "clip_max_s": 20}}


def test_workspace_settings_validation(client, settings_body):
    assert client.patch("/api/workspace", json=settings_body).status_code == 200
    assert client.patch("/api/workspace", json={"settings": {"nonsense": 1}}).status_code == 422
    assert client.patch("/api/workspace", json={"settings": {"clip_min_s": 50, "clip_max_s": 20}}).status_code == 422
    assert client.patch("/api/workspace", json={"settings": {"platforms": ["myspace"]}}).status_code == 422
    r = client.patch("/api/workspace", json={"settings": {"auto_approve_score": 85, "platforms": ["tiktok", "x"]}}).json()
    assert r["settings"]["auto_approve_score"] == 85 and r["settings"]["platforms"] == ["tiktok", "x"] and r["settings"]["clip_min_s"] == 8
